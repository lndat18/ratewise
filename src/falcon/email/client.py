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

_FOLDER_RE = re.compile(rb'\((?P<flags>.*?)\) "(?P<delim>.*?)" (?P<name>.*)')


class ImapClient:
    def __init__(self, config: ImapConfig, timeout: float = 30.0):
        self._config = config
        self._timeout = timeout
        self._conn: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "ImapClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        cfg = self._config
        self._conn = imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=self._timeout)
        self._conn.login(cfg.user, cfg.password)

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.logout()
        except imaplib.IMAP4.error:
            pass
        self._conn = None

    @property
    def conn(self) -> imaplib.IMAP4_SSL:
        if self._conn is None:
            raise RuntimeError("Chưa kết nối. Gọi connect() hoặc dùng `with`.")
        return self._conn

    def list_folders(self) -> list[str]:
        typ, data = self.conn.list()
        if typ != "OK":
            raise imaplib.IMAP4.error(f"LIST thất bại: {typ}")
        folders = []
        for raw in data:
            m = _FOLDER_RE.match(raw) if raw else None
            if m:
                folders.append(m["name"].decode().strip('"'))
        return folders

    def search(self, folder: str, *criteria: str) -> list[bytes]:
        """Tìm UID theo tiêu chí IMAP, vd search("INBOX", "SUBJECT", '"AE-49270"').

        Dùng UID (ổn định) thay vì số thứ tự.
        """
        typ, _ = self.conn.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"Không mở được folder {folder!r}")
        typ, data = self.conn.uid("SEARCH", None, *criteria)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SEARCH thất bại: {typ}")
        return data[0].split()

    def fetch(self, uid: bytes) -> EmailMessage:
        """Tải toàn bộ thư (không đánh dấu đã đọc). Folder phải được select trước."""
        typ, data = self.conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or data[0] is None:
            raise imaplib.IMAP4.error(f"FETCH UID {uid!r} thất bại")
        return message_from_bytes(data[0][1], policy=policy.default)
