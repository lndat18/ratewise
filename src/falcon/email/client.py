"""IMAP client chỉ đọc cho hộp thư (IONOS).

- Luôn mở folder ở chế độ readonly và fetch bằng BODY.PEEK, nên không làm
  đổi trạng thái đã đọc của mail.
- Dùng như context manager: `with ImapClient(cfg) as c: ...`
"""

import imaplib
import re
from email import message_from_bytes, policy
from email.message import EmailMessage

from falcon.config import ImapConfig
from falcon.email.models import FolderStatus

_FOLDER_RE = re.compile(rb'\((?P<flags>.*?)\) "(?P<delim>.*?)" (?P<name>.*)')


class ImapClient:
    """Kết nối IMAP chỉ đọc; dùng như context manager."""

    def __init__(self, config: ImapConfig, timeout: float = 30.0) -> None:
        """Lưu cấu hình; chưa kết nối cho tới khi gọi `connect()`."""
        self._config = config
        self._timeout = timeout
        self._conn: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> ImapClient:
        """Kết nối và trả chính client."""
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        """Đóng kết nối."""
        self.close()

    def connect(self) -> None:
        """Mở kết nối SSL và đăng nhập."""
        cfg = self._config
        self._conn = imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=self._timeout)
        self._conn.login(cfg.user, cfg.password)

    def close(self) -> None:
        """Đăng xuất và đóng kết nối (an toàn khi gọi lại)."""
        if self._conn is None:
            return
        try:
            self._conn.logout()
        except imaplib.IMAP4.error:
            pass
        self._conn = None

    @property
    def conn(self) -> imaplib.IMAP4_SSL:
        """Kết nối IMAP đang mở."""
        if self._conn is None:
            raise RuntimeError("Chưa kết nối. Gọi connect() hoặc dùng `with`.")
        return self._conn

    def list_folders(self) -> list[str]:
        """Liệt kê tên các folder IMAP."""
        typ, data = self.conn.list()
        if typ != "OK":
            raise imaplib.IMAP4.error(f"LIST thất bại: {typ}")
        folders = []
        for raw in data:
            m = _FOLDER_RE.match(raw) if isinstance(raw, bytes) else None
            if m:
                folders.append(m["name"].decode().strip('"'))
        return folders

    def search(self, folder: str, *criteria: str) -> list[bytes]:
        """Tìm UID theo tiêu chí IMAP.

        Ví dụ: `search("INBOX", "SUBJECT", '"AE-49270"')`.

        Dùng UID (ổn định) thay vì số thứ tự.
        """
        typ, _ = self.conn.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"Không mở được folder {folder!r}")
        typ, data = self.conn.uid("SEARCH", None, *criteria)  # type: ignore[arg-type]  # typeshed thiếu None
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SEARCH thất bại: {typ}")
        return [bytes(raw) for raw in (data[0] or b"").split()]

    def open_folder(self, folder: str) -> FolderStatus:
        """Mở folder ở chế độ readonly và đọc UIDVALIDITY/UIDNEXT.

        Args:
            folder: Tên folder IMAP.

        Returns:
            UIDVALIDITY và UIDNEXT do server báo khi SELECT.

        Raises:
            imaplib.IMAP4.error: Không mở được folder hoặc server không báo
                UIDVALIDITY/UIDNEXT.

        """
        typ, _ = self.conn.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"Không mở được folder {folder!r}")
        return FolderStatus(
            uidvalidity=self._read_select_value("UIDVALIDITY"),
            uidnext=self._read_select_value("UIDNEXT"),
        )

    def search_subject_since(self, min_uid: int, subject_fragment: str) -> list[int]:
        """Tìm UID >= min_uid có tiêu đề chứa chuỗi con; folder phải được mở trước.

        Args:
            min_uid: UID nhỏ nhất cần lấy. Server luôn trả thêm mail cuối với
                cú pháp `N:*`, nên người gọi phải tự lọc UID nhỏ hơn.
            subject_fragment: Chuỗi con (không có dấu nháy) cần khớp trong tiêu đề.

        Returns:
            Danh sách UID tăng dần.

        """
        typ, data = self.conn.uid(
            "SEARCH",
            None,  # type: ignore[arg-type]  # typeshed thiếu None cho charset
            "UID",
            f"{min_uid}:*",
            "SUBJECT",
            f'"{subject_fragment}"',
        )
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SEARCH thất bại: {typ}")
        return sorted(int(raw) for raw in (data[0] or b"").split())

    def _read_select_value(self, name: str) -> int:
        _, data = self.conn.response(name)
        if not data or data[0] is None:
            raise imaplib.IMAP4.error(f"Server không báo {name}")
        return int(data[-1])

    def fetch(self, uid: bytes | int) -> EmailMessage:
        """Tải toàn bộ thư (không đánh dấu đã đọc). Folder phải được select trước."""
        uid_text = uid.decode() if isinstance(uid, bytes) else str(uid)
        typ, data = self.conn.uid("FETCH", uid_text, "(BODY.PEEK[])")
        if typ != "OK" or not data or data[0] is None:
            raise imaplib.IMAP4.error(f"FETCH UID {uid!r} thất bại")
        return message_from_bytes(data[0][1], policy=policy.default)
