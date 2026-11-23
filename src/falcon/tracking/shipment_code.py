"""Nhận diện mã shipment (vd. `AE-49270`) trong tiêu đề email."""

import re

_SHIPMENT_CODE_RE = re.compile(r"(?<![A-Za-z0-9])AE-\d{5}(?!\d)", re.IGNORECASE)


def extract_shipment_codes(subject: str) -> list[str]:
    """Tìm các mã shipment hợp lệ trong tiêu đề.

    Không khớp `AE-1234`, `AE-123456`, `XAE-12345`.

    Args:
        subject: Tiêu đề email (giữ nguyên `Re:`/`Fw:`).

    Returns:
        Mã in hoa, không trùng, giữ thứ tự xuất hiện đầu tiên.

    """
    codes = (match.group(0).upper() for match in _SHIPMENT_CODE_RE.finditer(subject))
    return list(dict.fromkeys(codes))
