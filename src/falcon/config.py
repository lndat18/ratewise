"""Đọc cấu hình từ biến môi trường / file .env (không commit bí mật)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường {name} (xem .env)")
    return value


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)  # repr=False: không lộ mật khẩu khi log

    @classmethod
    def from_env(cls) -> "ImapConfig":
        return cls(
            host=_require("IMAP_HOST"),
            port=int(os.environ.get("IMAP_PORT", "993")),
            user=_require("IMAP_USER"),
            password=_require("IMAP_PASSWORD"),
        )
