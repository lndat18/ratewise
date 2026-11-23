"""Đồng bộ email từ IMAP vào PostgreSQL theo UID (idempotent, append-only)."""

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from falcon.email.models import FolderStatus
from falcon.tracking.models import ParsedAttachment
from falcon.tracking.parser import parse_email
from falcon.tracking.repository import TrackingRepository
from falcon.tracking.shipment_code import extract_shipment_codes
from falcon.tracking.storage import store_attachment

logger = logging.getLogger(__name__)

SEARCH_SUBJECT_FRAGMENT = "AE-"


class MailSource(Protocol):
    """Nguồn mail chỉ đọc; `ImapClient` thỏa Protocol này, test dùng fake."""

    def open_folder(self, folder: str) -> FolderStatus:
        """Mở folder readonly và trả UIDVALIDITY/UIDNEXT."""
        ...

    def search_subject_since(self, min_uid: int, subject_fragment: str) -> list[int]:
        """Tìm UID >= min_uid có tiêu đề chứa chuỗi con (có thể trả thừa UID nhỏ hơn)."""
        ...

    def fetch(self, uid: int) -> EmailMessage:
        """Tải toàn bộ một thư."""
        ...


class FolderSyncResult(BaseModel):
    """Kết quả đồng bộ một folder."""

    folder: str
    stored: int = 0
    already_present: int = 0
    skipped_no_code: int = 0
    failed_uid: int | None = None

    @property
    def ok(self) -> bool:
        """True nếu folder xử lý xong, không có mail lỗi."""
        return self.failed_uid is None


def sync_folder(
    source: MailSource,
    repository: TrackingRepository,
    folder: str,
    data_dir: Path,
) -> FolderSyncResult:
    """Đồng bộ một folder.

    `UIDVALIDITY` đổi (hoặc chưa có state) thì quét lại từ UID 1. Một email lỗi
    parse/ghi làm rollback email đó, dừng folder và không nâng `last_uid`.
    Lỗi IMAP khi mở/tìm/fetch được ném tiếp để cả lượt sync fail.

    Args:
        source: Nguồn mail.
        repository: Repository PostgreSQL.
        folder: Tên folder IMAP.
        data_dir: Thư mục gốc lưu file đính kèm.

    Returns:
        Kết quả đồng bộ folder.

    """
    status = source.open_folder(folder)
    state = repository.get_sync_state(folder)
    last_uid = state.last_uid if state and state.uidvalidity == status.uidvalidity else 0
    result = FolderSyncResult(folder=folder)

    candidates = source.search_subject_since(last_uid + 1, SEARCH_SUBJECT_FRAGMENT)
    for uid in sorted(uid for uid in set(candidates) if uid > last_uid):
        raw = source.fetch(uid)
        if not _ingest_one(repository, raw, folder, status.uidvalidity, uid, data_dir, result):
            result.failed_uid = uid
            return result

    # UIDNEXT đọc trước SEARCH: mail đến giữa chừng được lấy ở lượt sau.
    repository.save_sync_state(folder, status.uidvalidity, status.uidnext - 1)
    return result


def _ingest_one(
    repository: TrackingRepository,
    raw: EmailMessage,
    folder: str,
    uidvalidity: int,
    uid: int,
    data_dir: Path,
    result: FolderSyncResult,
) -> bool:
    """Parse và ghi một email; trả False nếu lỗi (đã rollback và log)."""
    try:
        parsed = parse_email(raw)
        codes = extract_shipment_codes(parsed.subject)
        if not codes:
            result.skipped_no_code += 1
            return True

        def _store(attachment: ParsedAttachment) -> None:
            store_attachment(data_dir, attachment.sha256, attachment.content)

        is_new = repository.ingest_email(parsed, codes, folder, uidvalidity, uid, _store)
    except Exception as exc:  # noqa: BLE001 - mọi lỗi của một mail đều dừng folder
        # Chỉ log kiểu lỗi: thông điệp có thể chứa nội dung mail.
        logger.error("Lỗi xử lý mail folder=%r uid=%d: %s", folder, uid, type(exc).__name__)
        return False
    if is_new:
        result.stored += 1
    else:
        result.already_present += 1
    return True


def sync_all(
    source: MailSource,
    repository: TrackingRepository,
    folders: Sequence[str],
    data_dir: Path,
) -> list[FolderSyncResult]:
    """Đồng bộ lần lượt các folder; folder có mail lỗi không chặn folder khác.

    Args:
        source: Nguồn mail.
        repository: Repository PostgreSQL.
        folders: Danh sách folder cần đồng bộ.
        data_dir: Thư mục gốc lưu file đính kèm.

    Returns:
        Kết quả từng folder.

    """
    return [sync_folder(source, repository, folder, data_dir) for folder in folders]


def run_sync(
    repository: TrackingRepository,
    open_source: Callable[[], AbstractContextManager[MailSource]],
    folders: Sequence[str],
    data_dir: Path,
) -> list[FolderSyncResult] | None:
    """Chạy một lượt sync cho mọi folder dưới advisory lock.

    Args:
        repository: Repository PostgreSQL.
        open_source: Mở kết nối nguồn mail (context manager), gọi sau khi có lock.
        folders: Danh sách folder cần đồng bộ.
        data_dir: Thư mục gốc lưu file đính kèm.

    Returns:
        Kết quả từng folder, hoặc `None` nếu worker khác đang chạy.

    """
    if not repository.try_sync_lock():
        logger.info("Worker khác đang sync, bỏ qua lượt này")
        return None
    try:
        with open_source() as source:
            return sync_all(source, repository, folders, data_dir)
    finally:
        repository.release_sync_lock()
