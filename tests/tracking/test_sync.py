"""Test sync với MailSource và repository giả (không IMAP/DB)."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from email.message import EmailMessage
from pathlib import Path
from typing import cast

import pytest
from conftest import MessageFactory

from falcon.email.models import FolderStatus
from falcon.tracking.models import FolderSyncState, ParsedAttachment, ParsedEmail
from falcon.tracking.repository import TrackingRepository
from falcon.tracking.sync import run_sync, sync_all, sync_folder


class FakeRepository:
    """Mô phỏng ngữ nghĩa idempotent của `TrackingRepository` trong bộ nhớ."""

    def __init__(self) -> None:
        self.emails: dict[str, ParsedEmail] = {}
        self.sources: set[tuple[str, int, int]] = set()
        self.links: set[tuple[str, str]] = set()
        self.state: dict[str, FolderSyncState] = {}
        self.lock_available = True
        self.lock_calls: list[str] = []
        self.fail_on_message_id: str | None = None

    def try_sync_lock(self) -> bool:
        self.lock_calls.append("try")
        return self.lock_available

    def release_sync_lock(self) -> None:
        self.lock_calls.append("release")

    def get_sync_state(self, folder: str) -> FolderSyncState | None:
        return self.state.get(folder)

    def save_sync_state(self, folder: str, uidvalidity: int, last_uid: int) -> None:
        self.state[folder] = FolderSyncState(uidvalidity=uidvalidity, last_uid=last_uid)

    def ingest_email(
        self,
        parsed: ParsedEmail,
        shipment_codes: list[str],
        folder: str,
        uidvalidity: int,
        uid: int,
        store_attachment: Callable[[ParsedAttachment], None],
    ) -> bool:
        if parsed.message_id == self.fail_on_message_id:
            raise RuntimeError("secret body content")
        is_new = parsed.message_id not in self.emails
        if is_new:
            for attachment in parsed.attachments:
                store_attachment(attachment)
            self.emails[parsed.message_id] = parsed
        self.sources.add((folder, uidvalidity, uid))
        self.links.update((code, parsed.message_id) for code in shipment_codes)
        return is_new


class FakeSource:
    """Nguồn mail giả: mỗi folder có UIDVALIDITY, UIDNEXT và các thư theo UID."""

    def __init__(self) -> None:
        self.folders: dict[str, tuple[int, int, dict[int, EmailMessage]]] = {}
        self.current = ""
        self.searches: list[tuple[str, int, str]] = []
        self.fetched: list[tuple[str, int]] = []

    def add_folder(
        self, name: str, uidvalidity: int, uidnext: int, mails: dict[int, EmailMessage]
    ) -> None:
        self.folders[name] = (uidvalidity, uidnext, mails)

    def open_folder(self, folder: str) -> FolderStatus:
        self.current = folder
        validity, uidnext, _ = self.folders[folder]
        return FolderStatus(uidvalidity=validity, uidnext=uidnext)

    def search_subject_since(self, min_uid: int, subject_fragment: str) -> list[int]:
        self.searches.append((self.current, min_uid, subject_fragment))
        mails = self.folders[self.current][2]
        uids = sorted(u for u in mails if u >= min_uid)
        # IMAP `N:*` luôn trả ít nhất mail cuối cùng dù UID < N.
        if not uids and mails:
            uids = [max(mails)]
        return uids

    def fetch(self, uid: int) -> EmailMessage:
        self.fetched.append((self.current, uid))
        return self.folders[self.current][2][uid]


def _repo(fake: FakeRepository) -> TrackingRepository:
    return cast("TrackingRepository", fake)


def test_sync_stores_and_advances_cursor(tmp_path: Path, make_message: MessageFactory) -> None:
    repo, source = FakeRepository(), FakeSource()
    source.add_folder(
        "INBOX", 7, 3, {1: make_message(message_id="<a>"), 2: make_message("AE-11111", "<b>")}
    )

    result = sync_folder(source, _repo(repo), "INBOX", tmp_path)

    assert result.ok
    assert result.stored == 2
    assert repo.state["INBOX"] == FolderSyncState(uidvalidity=7, last_uid=2)
    assert source.searches == [("INBOX", 1, "AE-")]
    assert repo.links == {("AE-49270", "<a>"), ("AE-11111", "<b>")}


def test_sync_twice_is_idempotent(tmp_path: Path, make_message: MessageFactory) -> None:
    repo, source = FakeRepository(), FakeSource()
    source.add_folder("INBOX", 7, 2, {1: make_message()})

    first = sync_folder(source, _repo(repo), "INBOX", tmp_path)
    snapshot = (dict(repo.emails), set(repo.sources), set(repo.links))
    fetched_before = len(source.fetched)
    second = sync_folder(source, _repo(repo), "INBOX", tmp_path)

    assert first.stored == 1
    assert second.stored == 0
    assert (dict(repo.emails), set(repo.sources), set(repo.links)) == snapshot
    # UID <= last_uid trả thừa bởi IMAP bị lọc, không fetch lại.
    assert len(source.fetched) == fetched_before


def test_new_mail_after_first_sync_is_fetched(tmp_path: Path, make_message: MessageFactory) -> None:
    repo, source = FakeRepository(), FakeSource()
    source.add_folder("INBOX", 7, 2, {1: make_message(message_id="<a>")})
    sync_folder(source, _repo(repo), "INBOX", tmp_path)

    source.add_folder(
        "INBOX", 7, 3, {1: make_message(message_id="<a>"), 2: make_message(message_id="<b>")}
    )
    result = sync_folder(source, _repo(repo), "INBOX", tmp_path)

    assert result.stored == 1
    assert source.searches[-1] == ("INBOX", 2, "AE-")
    assert repo.state["INBOX"].last_uid == 2


def test_uidvalidity_change_rescans_without_duplicates(
    tmp_path: Path, make_message: MessageFactory
) -> None:
    repo, source = FakeRepository(), FakeSource()
    source.add_folder(
        "INBOX", 7, 3, {1: make_message(message_id="<a>"), 2: make_message(message_id="<b>")}
    )
    sync_folder(source, _repo(repo), "INBOX", tmp_path)

    # UID đánh số lại, cùng nội dung.
    source.add_folder(
        "INBOX", 8, 3, {1: make_message(message_id="<a>"), 2: make_message(message_id="<b>")}
    )
    result = sync_folder(source, _repo(repo), "INBOX", tmp_path)

    assert source.searches[-1] == ("INBOX", 1, "AE-")
    assert result.stored == 0
    assert result.already_present == 2
    assert len(repo.emails) == 2
    assert repo.state["INBOX"] == FolderSyncState(uidvalidity=8, last_uid=2)
    assert {s[1] for s in repo.sources} == {7, 8}


def test_same_mail_in_two_folders_is_one_email(
    tmp_path: Path, make_message: MessageFactory
) -> None:
    repo, source = FakeRepository(), FakeSource()
    source.add_folder("INBOX", 1, 2, {1: make_message()})
    source.add_folder("Sent Items", 5, 10, {9: make_message()})

    results = sync_all(source, _repo(repo), ["INBOX", "Sent Items"], tmp_path)

    assert [r.stored for r in results] == [1, 0]
    assert [r.already_present for r in results] == [0, 1]
    assert len(repo.emails) == 1
    assert repo.sources == {("INBOX", 1, 1), ("Sent Items", 5, 9)}


def test_mail_without_valid_code_is_skipped(tmp_path: Path, make_message: MessageFactory) -> None:
    repo, source = FakeRepository(), FakeSource()
    # SEARCH khớp substring "AE-" nhưng không phải mã hợp lệ.
    source.add_folder("INBOX", 1, 2, {1: make_message(subject="Meeting AE-12")})

    result = sync_folder(source, _repo(repo), "INBOX", tmp_path)

    assert result.ok
    assert result.skipped_no_code == 1
    assert repo.emails == {}
    assert repo.state["INBOX"].last_uid == 1


def test_failed_mail_keeps_cursor_and_other_folders_continue(
    tmp_path: Path, make_message: MessageFactory, caplog: pytest.LogCaptureFixture
) -> None:
    repo, source = FakeRepository(), FakeSource()
    repo.fail_on_message_id = "<bad>"
    source.add_folder(
        "INBOX",
        1,
        4,
        {
            1: make_message(message_id="<ok1>"),
            2: make_message(message_id="<bad>"),
            3: make_message(message_id="<ok3>"),
        },
    )
    source.add_folder("Sent Items", 2, 2, {1: make_message("AE-22222", "<sent>")})

    with caplog.at_level(logging.ERROR):
        results = sync_all(source, _repo(repo), ["INBOX", "Sent Items"], tmp_path)

    inbox, sent = results
    assert not inbox.ok
    assert inbox.failed_uid == 2
    assert inbox.stored == 1
    assert "INBOX" not in repo.state  # không nâng last_uid
    assert "<ok3>" not in repo.emails  # dừng folder tại mail lỗi
    assert sent.ok
    assert repo.state["Sent Items"].last_uid == 1
    log = caplog.text
    assert "uid=2" in log
    assert "INBOX" in log
    assert "secret body content" not in log


def test_failed_mail_retried_next_run(tmp_path: Path, make_message: MessageFactory) -> None:
    repo, source = FakeRepository(), FakeSource()
    repo.fail_on_message_id = "<bad>"
    source.add_folder(
        "INBOX", 1, 3, {1: make_message(message_id="<ok>"), 2: make_message(message_id="<bad>")}
    )
    sync_folder(source, _repo(repo), "INBOX", tmp_path)

    repo.fail_on_message_id = None
    result = sync_folder(source, _repo(repo), "INBOX", tmp_path)

    assert result.ok
    assert set(repo.emails) == {"<ok>", "<bad>"}
    assert repo.state["INBOX"].last_uid == 2


def test_cursor_uses_uidnext_read_before_search(
    tmp_path: Path, make_message: MessageFactory
) -> None:
    repo, source = FakeRepository(), FakeSource()
    # UIDNEXT=3 lúc SELECT; mail UID 3 đến sau đó không được đẩy cursor vượt 2.
    source.add_folder(
        "INBOX", 1, 3, {1: make_message(message_id="<a>"), 2: make_message(message_id="<b>")}
    )
    sync_folder(source, _repo(repo), "INBOX", tmp_path)
    assert repo.state["INBOX"].last_uid == 2


def test_attachment_written_to_disk_once(tmp_path: Path, make_message: MessageFactory) -> None:
    repo, source = FakeRepository(), FakeSource()
    msg = make_message(attachments=[("a.pdf", b"payload")])
    source.add_folder("INBOX", 1, 2, {1: msg})
    sync_folder(source, _repo(repo), "INBOX", tmp_path)
    files = list((tmp_path / "attachments").iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"payload"


def test_imap_error_propagates(tmp_path: Path) -> None:
    class Broken(FakeSource):
        def open_folder(self, folder: str) -> FolderStatus:
            raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        sync_folder(Broken(), _repo(FakeRepository()), "INBOX", tmp_path)


def test_run_sync_skips_when_lock_held(tmp_path: Path) -> None:
    repo = FakeRepository()
    repo.lock_available = False
    opened: list[bool] = []

    @contextmanager
    def open_source() -> Iterator[FakeSource]:
        opened.append(True)
        yield FakeSource()

    assert run_sync(_repo(repo), open_source, ["INBOX"], tmp_path) is None
    assert opened == []  # không mở IMAP khi không có lock
    assert repo.lock_calls == ["try"]  # không nhả lock không phải của mình


def test_run_sync_releases_lock_on_error(tmp_path: Path) -> None:
    repo = FakeRepository()

    @contextmanager
    def open_source() -> Iterator[FakeSource]:
        raise ConnectionError("login failed")
        yield FakeSource()  # pragma: no cover

    with pytest.raises(ConnectionError):
        run_sync(_repo(repo), open_source, ["INBOX"], tmp_path)
    assert repo.lock_calls == ["try", "release"]


def test_run_sync_returns_results_and_releases(
    tmp_path: Path, make_message: MessageFactory
) -> None:
    repo, source = FakeRepository(), FakeSource()
    source.add_folder("INBOX", 1, 2, {1: make_message()})

    @contextmanager
    def open_source() -> Iterator[FakeSource]:
        yield source

    results = run_sync(_repo(repo), open_source, ["INBOX"], tmp_path)
    assert results is not None
    assert results[0].stored == 1
    assert repo.lock_calls == ["try", "release"]
