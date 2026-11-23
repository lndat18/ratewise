"""Truy cập mailbox qua IMAP (chỉ đọc)."""

from falcon.email.client import ImapClient
from falcon.email.models import FolderStatus

__all__ = ["FolderStatus", "ImapClient"]
