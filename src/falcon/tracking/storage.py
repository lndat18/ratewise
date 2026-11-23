"""Ghi file đính kèm ra đĩa theo sha256 (content-addressed)."""

import os
import re
import tempfile
from pathlib import Path

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def attachment_path(data_dir: Path, sha256: str) -> Path:
    """Dựng đường dẫn file đính kèm từ sha256.

    Tên file người gửi không bao giờ tham gia vào đường dẫn.

    Args:
        data_dir: Thư mục gốc `DATA_DIR`.
        sha256: Hash hex 64 ký tự thường.

    Returns:
        `DATA_DIR/attachments/<sha256>`.

    Raises:
        ValueError: `sha256` không đúng định dạng.

    """
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError("sha256 không hợp lệ")
    return data_dir / "attachments" / sha256


def store_attachment(data_dir: Path, sha256: str, content: bytes) -> Path:
    """Ghi nội dung ra file tạm rồi rename nguyên tử; bỏ qua nếu đã tồn tại.

    Args:
        data_dir: Thư mục gốc `DATA_DIR`.
        sha256: Hash của `content`.
        content: Nội dung file.

    Returns:
        Đường dẫn file đã lưu.

    Raises:
        OSError: Lỗi ghi đĩa (vd. đầy đĩa).

    """
    target = attachment_path(data_dir, sha256)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target
