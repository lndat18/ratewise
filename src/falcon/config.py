"""Đọc cấu hình từ biến môi trường / file .env (không commit bí mật)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường {name} (xem .env)")
    return value


@dataclass(frozen=True)
class ImapConfig:
    """Thông tin đăng nhập IMAP."""

    host: str
    port: int
    user: str
    password: str = field(repr=False)  # repr=False: không lộ mật khẩu khi log

    @classmethod
    def from_env(cls) -> ImapConfig:
        """Đọc `IMAP_HOST/PORT/USER/PASSWORD` từ môi trường."""
        return cls(
            host=_require("IMAP_HOST"),
            port=int(os.environ.get("IMAP_PORT", "993")),
            user=_require("IMAP_USER"),
            password=_require("IMAP_PASSWORD"),
        )


class DatabaseConfig(BaseModel):
    """Cấu hình kết nối PostgreSQL."""

    model_config = ConfigDict(frozen=True)

    database_url: str = Field(repr=False)  # có thể chứa mật khẩu

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """Đọc `DATABASE_URL` (bắt buộc)."""
        return cls(database_url=_require("DATABASE_URL"))


class SyncConfig(BaseModel):
    """Cấu hình worker đồng bộ email."""

    model_config = ConfigDict(frozen=True)

    data_dir: Path
    folders: tuple[str, ...]
    interval_seconds: int = Field(gt=0)

    @classmethod
    def from_env(cls) -> SyncConfig:
        """Đọc `DATA_DIR`, `SYNC_FOLDERS`, `SYNC_INTERVAL_SECONDS` kèm mặc định."""
        raw_folders = os.environ.get("SYNC_FOLDERS") or "INBOX,Sent Items"
        folders = tuple(name.strip() for name in raw_folders.split(",") if name.strip())
        data_dir = os.environ.get("DATA_DIR") or "~/falcon_data"
        return cls(
            data_dir=Path(data_dir).expanduser(),
            folders=folders,
            interval_seconds=int(os.environ.get("SYNC_INTERVAL_SECONDS") or "300"),
        )
