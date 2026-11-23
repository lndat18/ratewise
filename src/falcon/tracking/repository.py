"""Toàn bộ SQL của tracking: migrate, ghi email, sync_state, truy vấn cho web."""

import re
from collections.abc import Callable
from pathlib import Path

from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from falcon.tracking.models import (
    AttachmentInfo,
    EmailView,
    FolderSyncState,
    ParsedAttachment,
    ParsedEmail,
    ShipmentDetail,
    ShipmentSummary,
    StoredAttachment,
)

SYNC_LOCK_KEY = 0x66616C63  # "falc": khóa advisory của sync worker
_MIGRATE_LOCK_KEY = 0x66616C64
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_FILE_RE = re.compile(r"(?P<version>\d+)_.+\.sql")


def apply_migrations(conn: Connection[DictRow], migrations_dir: Path = MIGRATIONS_DIR) -> list[int]:
    """Chạy các migration `NNN_*.sql` chưa áp dụng, mỗi file một transaction.

    Args:
        conn: Kết nối ở chế độ autocommit.
        migrations_dir: Thư mục chứa file migration.

    Returns:
        Danh sách version vừa áp dụng (rỗng nếu đã cập nhật).

    """
    conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATE_LOCK_KEY,))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version int PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        applied: list[int] = []
        for version, path in _list_migration_files(migrations_dir):
            if version in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(version)
        return applied
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATE_LOCK_KEY,))


def _list_migration_files(migrations_dir: Path) -> list[tuple[int, Path]]:
    found = []
    for path in migrations_dir.iterdir():
        match = _MIGRATION_FILE_RE.fullmatch(path.name)
        if match:
            found.append((int(match["version"]), path))
    return sorted(found)


def make_dict_connection(database_url: str) -> Connection[DictRow]:
    """Mở kết nối autocommit trả hàng dạng dict.

    Args:
        database_url: URL PostgreSQL.

    Returns:
        Kết nối mới; người gọi tự đóng.

    """
    return Connection.connect(database_url, autocommit=True, row_factory=dict_row)


class TrackingRepository:
    """Truy cập PostgreSQL cho sync worker và web (SQL thuần)."""

    def __init__(self, conn: Connection[DictRow]) -> None:
        """Khởi tạo với kết nối autocommit trả hàng dạng dict."""
        self._conn = conn

    def try_sync_lock(self) -> bool:
        """Thử lấy advisory lock của sync worker (theo phiên).

        Returns:
            True nếu lấy được; False nếu worker khác đang giữ.

        """
        row = self._conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS ok", (SYNC_LOCK_KEY,)
        ).fetchone()
        return bool(row and row["ok"])

    def release_sync_lock(self) -> None:
        """Nhả advisory lock của sync worker."""
        self._conn.execute("SELECT pg_advisory_unlock(%s)", (SYNC_LOCK_KEY,))

    def get_sync_state(self, folder: str) -> FolderSyncState | None:
        """Đọc con trỏ đồng bộ của folder, `None` nếu chưa có."""
        row = self._conn.execute(
            "SELECT uidvalidity, last_uid FROM sync_state WHERE folder = %s", (folder,)
        ).fetchone()
        return FolderSyncState(**row) if row else None

    def save_sync_state(self, folder: str, uidvalidity: int, last_uid: int) -> None:
        """Ghi (upsert) con trỏ đồng bộ của folder."""
        self._conn.execute(
            "INSERT INTO sync_state (folder, uidvalidity, last_uid) VALUES (%s, %s, %s) "
            "ON CONFLICT (folder) DO UPDATE SET "
            "uidvalidity = EXCLUDED.uidvalidity, last_uid = EXCLUDED.last_uid",
            (folder, uidvalidity, last_uid),
        )

    def ingest_email(
        self,
        parsed: ParsedEmail,
        shipment_codes: list[str],
        folder: str,
        uidvalidity: int,
        uid: int,
        store_attachment: Callable[[ParsedAttachment], None],
    ) -> bool:
        """Ghi một email trong một transaction (idempotent).

        Args:
            parsed: Email đã parse.
            shipment_codes: Mã shipment tìm thấy trong subject (không rỗng).
            folder: Folder nguồn.
            uidvalidity: UIDVALIDITY của folder lúc fetch.
            uid: UID trong folder.
            store_attachment: Ghi nội dung file ra đĩa; chỉ gọi khi email mới.

        Returns:
            True nếu email mới được tạo; False nếu đã có (chỉ bổ sung nguồn/liên kết).

        """
        with self._conn.transaction():
            email_id, is_new = self._upsert_email(parsed)
            self._conn.execute(
                "INSERT INTO email_sources (email_id, folder, uidvalidity, uid) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (folder, uidvalidity, uid) DO NOTHING",
                (email_id, folder, uidvalidity, uid),
            )
            for code in shipment_codes:
                self._link_shipment(email_id, code)
            if is_new:
                for attachment in parsed.attachments:
                    store_attachment(attachment)
                    self._insert_attachment(email_id, attachment)
        return is_new

    def _upsert_email(self, parsed: ParsedEmail) -> tuple[int, bool]:
        row = self._conn.execute(
            "INSERT INTO emails (message_id, subject, from_addr, to_addrs, cc_addrs, sent_at, "
            "body_text) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (message_id) DO NOTHING RETURNING id",
            (
                parsed.message_id,
                parsed.subject,
                parsed.from_addr,
                parsed.to_addrs,
                parsed.cc_addrs,
                parsed.sent_at,
                parsed.body_text,
            ),
        ).fetchone()
        if row:
            return row["id"], True
        existing = self._conn.execute(
            "SELECT id FROM emails WHERE message_id = %s", (parsed.message_id,)
        ).fetchone()
        if existing is None:
            raise RuntimeError("Email biến mất giữa INSERT và SELECT")
        return existing["id"], False

    def _link_shipment(self, email_id: int, code: str) -> None:
        row = self._conn.execute(
            "INSERT INTO shipments (code) VALUES (%s) "
            "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id",
            (code,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Upsert shipment không trả id")
        self._conn.execute(
            "INSERT INTO shipment_emails (shipment_id, email_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (row["id"], email_id),
        )

    def _insert_attachment(self, email_id: int, attachment: ParsedAttachment) -> None:
        self._conn.execute(
            "INSERT INTO attachments (email_id, filename, content_type, size_bytes, sha256) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                email_id,
                attachment.filename,
                attachment.content_type,
                attachment.size_bytes,
                attachment.sha256,
            ),
        )

    def list_shipments(self, query: str | None = None) -> list[ShipmentSummary]:
        """Liệt kê shipment, mail mới nhất lên đầu.

        Args:
            query: Chuỗi con (không phân biệt hoa/thường) cần khớp trong `code`.

        Returns:
            Danh sách tóm tắt shipment.

        """
        pattern = "%"
        if query:
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
        rows = self._conn.execute(
            "SELECT s.code, l.email_count, l.sent_at AS latest_sent_at, "
            "l.subject AS latest_subject "
            "FROM shipments s CROSS JOIN LATERAL ("
            "  SELECT e.subject, e.sent_at, count(*) OVER () AS email_count "
            "  FROM shipment_emails se JOIN emails e ON e.id = se.email_id "
            "  WHERE se.shipment_id = s.id "
            "  ORDER BY e.sent_at DESC NULLS LAST, e.id DESC LIMIT 1"
            ") l "
            "WHERE s.code ILIKE %s ESCAPE '\\' "
            "ORDER BY l.sent_at DESC NULLS LAST, s.id DESC",
            (pattern,),
        ).fetchall()
        return [ShipmentSummary(**row) for row in rows]

    def get_shipment_detail(self, code: str) -> ShipmentDetail | None:
        """Lấy shipment và các email của nó theo `sent_at` tăng dần.

        Args:
            code: Mã shipment (chuẩn hóa in hoa tại đây).

        Returns:
            `ShipmentDetail`, hoặc `None` nếu không có shipment.

        """
        shipment = self._conn.execute(
            "SELECT id, code FROM shipments WHERE code = %s", (code.upper(),)
        ).fetchone()
        if shipment is None:
            return None
        rows = self._conn.execute(
            "SELECT e.id, e.subject, e.from_addr, e.to_addrs, e.sent_at, e.body_text "
            "FROM shipment_emails se JOIN emails e ON e.id = se.email_id "
            "WHERE se.shipment_id = %s ORDER BY e.sent_at ASC NULLS LAST, e.id",
            (shipment["id"],),
        ).fetchall()
        attachments = self._attachments_by_email([row["id"] for row in rows])
        emails = [EmailView(**row, attachments=attachments.get(row["id"], [])) for row in rows]
        return ShipmentDetail(code=shipment["code"], emails=emails)

    def _attachments_by_email(self, email_ids: list[int]) -> dict[int, list[AttachmentInfo]]:
        if not email_ids:
            return {}
        rows = self._conn.execute(
            "SELECT id, email_id, filename, content_type, size_bytes FROM attachments "
            "WHERE email_id = ANY(%s) ORDER BY id",
            (email_ids,),
        ).fetchall()
        grouped: dict[int, list[AttachmentInfo]] = {}
        for row in rows:
            grouped.setdefault(row["email_id"], []).append(
                AttachmentInfo(
                    id=row["id"],
                    filename=row["filename"],
                    content_type=row["content_type"],
                    size_bytes=row["size_bytes"],
                )
            )
        return grouped

    def get_attachment(self, attachment_id: int) -> StoredAttachment | None:
        """Lấy filename và sha256 của attachment, `None` nếu không có."""
        row = self._conn.execute(
            "SELECT filename, sha256 FROM attachments WHERE id = %s", (attachment_id,)
        ).fetchone()
        return StoredAttachment(**row) if row else None
