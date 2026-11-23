"""Integration với PostgreSQL thật; chỉ chạy khi có `TEST_DATABASE_URL`.

Mỗi test dùng một schema riêng (search_path) rồi xóa, nên không đụng dữ liệu thật.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from falcon.tracking.models import ParsedAttachment, ParsedEmail
from falcon.tracking.repository import (
    SYNC_LOCK_KEY,
    TrackingRepository,
    apply_migrations,
    make_dict_connection,
)

pytestmark = pytest.mark.integration

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def conn() -> Iterator[Connection[DictRow]]:
    if not TEST_DATABASE_URL:
        pytest.skip("cần TEST_DATABASE_URL")
    schema = f"t_{uuid.uuid4().hex}"
    admin = make_dict_connection(TEST_DATABASE_URL)
    admin.execute(f"CREATE SCHEMA {schema}")
    connection = make_dict_connection(TEST_DATABASE_URL)
    connection.execute(f"SET search_path TO {schema}")
    try:
        yield connection
    finally:
        connection.close()
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


@pytest.fixture
def repo(conn: Connection[DictRow]) -> TrackingRepository:
    apply_migrations(conn)
    return TrackingRepository(conn)


def _email(
    message_id: str = "<a@x>", subject: str = "AE-49270 hi", sent_at: datetime | None = None
) -> ParsedEmail:
    return ParsedEmail(
        message_id=message_id,
        subject=subject,
        from_addr="a@x.com",
        to_addrs=["b@x.com", "c@x.com"],
        cc_addrs=[],
        sent_at=sent_at,
        body_text="body",
        attachments=[],
    )


def _count(conn: Connection[DictRow], table: str) -> int:
    row = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()  # noqa: S608
    assert row is not None
    return int(row["n"])


def test_migrate_creates_tables_and_is_rerunnable(conn: Connection[DictRow]) -> None:
    assert apply_migrations(conn) == [1]
    assert apply_migrations(conn) == []
    tables = {
        r["table_name"]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        )
    }
    assert {
        "shipments",
        "emails",
        "email_sources",
        "shipment_emails",
        "attachments",
        "sync_state",
        "schema_migrations",
    } <= tables


def test_sync_state_roundtrip(repo: TrackingRepository) -> None:
    assert repo.get_sync_state("INBOX") is None
    repo.save_sync_state("INBOX", 5, 10)
    repo.save_sync_state("INBOX", 6, 0)
    state = repo.get_sync_state("INBOX")
    assert state is not None
    assert (state.uidvalidity, state.last_uid) == (6, 0)


def test_ingest_is_idempotent(repo: TrackingRepository, conn: Connection[DictRow]) -> None:
    stored: list[str] = []
    att = ParsedAttachment(
        filename="a.pdf",
        content_type="application/pdf",
        size_bytes=1,
        sha256="b" * 64,
        content=b"x",
    )
    parsed = _email().model_copy(update={"attachments": [att]})

    first = repo.ingest_email(
        parsed, ["AE-49270"], "INBOX", 1, 1, lambda a: stored.append(a.sha256)
    )
    again = repo.ingest_email(
        parsed, ["AE-49270"], "INBOX", 1, 1, lambda a: stored.append(a.sha256)
    )

    assert (first, again) == (True, False)
    assert stored == ["b" * 64]
    for table in ("emails", "email_sources", "shipments", "shipment_emails", "attachments"):
        assert _count(conn, table) == 1


def test_same_email_two_folders_and_two_shipments(
    repo: TrackingRepository, conn: Connection[DictRow]
) -> None:
    parsed = _email(subject="AE-11111 AE-22222")
    repo.ingest_email(parsed, ["AE-11111", "AE-22222"], "INBOX", 1, 1, lambda a: None)
    new = repo.ingest_email(parsed, ["AE-11111", "AE-22222"], "Sent Items", 9, 4, lambda a: None)

    assert new is False
    assert _count(conn, "emails") == 1
    assert _count(conn, "email_sources") == 2
    assert _count(conn, "shipment_emails") == 2


def test_ingest_failure_rolls_back_email(
    repo: TrackingRepository, conn: Connection[DictRow]
) -> None:
    att = ParsedAttachment(
        filename="a", content_type="x/y", size_bytes=1, sha256="c" * 64, content=b"x"
    )
    parsed = _email().model_copy(update={"attachments": [att]})

    def boom(_: ParsedAttachment) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        repo.ingest_email(parsed, ["AE-49270"], "INBOX", 1, 1, boom)

    for table in ("emails", "email_sources", "shipments", "shipment_emails", "attachments"):
        assert _count(conn, table) == 0


def test_list_shipments_order_count_and_filter(repo: TrackingRepository) -> None:
    t1 = datetime(2026, 11, 1, tzinfo=UTC)
    t2 = datetime(2026, 11, 2, tzinfo=UTC)
    t3 = datetime(2026, 11, 3, tzinfo=UTC)
    repo.ingest_email(
        _email("<1>", "AE-11111 old", t1), ["AE-11111"], "INBOX", 1, 1, lambda a: None
    )
    repo.ingest_email(_email("<2>", "AE-22222 a", t2), ["AE-22222"], "INBOX", 1, 2, lambda a: None)
    repo.ingest_email(_email("<3>", "AE-22222 b", t3), ["AE-22222"], "INBOX", 1, 3, lambda a: None)

    rows = repo.list_shipments()

    assert [r.code for r in rows] == ["AE-22222", "AE-11111"]
    assert rows[0].email_count == 2
    assert rows[0].latest_subject == "AE-22222 b"
    assert rows[0].latest_sent_at == t3
    assert [r.code for r in repo.list_shipments("111")] == ["AE-11111"]
    assert [r.code for r in repo.list_shipments("ae-2")] == ["AE-22222"]
    assert repo.list_shipments("%") == []  # ký tự đại diện được escape
    assert repo.list_shipments("_") == []


def test_detail_order_nulls_last_and_attachments(repo: TrackingRepository) -> None:
    att = ParsedAttachment(
        filename="a.pdf",
        content_type="application/pdf",
        size_bytes=3,
        sha256="d" * 64,
        content=b"x",
    )
    late = _email("<late>", "late", datetime(2026, 11, 5, tzinfo=UTC)).model_copy(
        update={"attachments": [att]}
    )
    early = _email("<early>", "early", datetime(2026, 11, 1, tzinfo=UTC))
    undated = _email("<none>", "undated", None)
    for uid, mail in enumerate([undated, late, early], start=1):
        repo.ingest_email(mail, ["AE-49270"], "INBOX", 1, uid, lambda a: None)

    detail = repo.get_shipment_detail("ae-49270")

    assert detail is not None
    assert [e.subject for e in detail.emails] == ["early", "late", "undated"]
    assert detail.emails[1].attachments[0].filename == "a.pdf"
    assert detail.emails[0].to_addrs == ["b@x.com", "c@x.com"]
    assert repo.get_shipment_detail("AE-00000") is None


def test_get_attachment(repo: TrackingRepository, conn: Connection[DictRow]) -> None:
    att = ParsedAttachment(
        filename="a.pdf", content_type="x/y", size_bytes=1, sha256="e" * 64, content=b"x"
    )
    repo.ingest_email(
        _email().model_copy(update={"attachments": [att]}),
        ["AE-49270"],
        "INBOX",
        1,
        1,
        lambda a: None,
    )
    row = conn.execute("SELECT id FROM attachments").fetchone()
    assert row is not None
    stored = repo.get_attachment(row["id"])
    assert stored is not None
    assert (stored.filename, stored.sha256) == ("a.pdf", "e" * 64)
    assert repo.get_attachment(row["id"] + 1000) is None


def test_advisory_lock_exclusive_between_sessions(repo: TrackingRepository) -> None:
    assert TEST_DATABASE_URL
    other_conn = make_dict_connection(TEST_DATABASE_URL)
    other = TrackingRepository(other_conn)
    try:
        assert repo.try_sync_lock() is True
        assert other.try_sync_lock() is False
        repo.release_sync_lock()
        assert other.try_sync_lock() is True
        other.release_sync_lock()
    finally:
        other_conn.close()
    assert SYNC_LOCK_KEY
