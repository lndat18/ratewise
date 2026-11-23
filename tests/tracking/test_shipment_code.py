"""Test nhận diện mã shipment trong subject."""

import pytest

from falcon.tracking.shipment_code import extract_shipment_codes


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("AE-49270", ["AE-49270"]),
        ("Re: Fw: AE-49270 pickup", ["AE-49270"]),
        ("ae-49270 lowercase", ["AE-49270"]),
        ("(AE-49270)", ["AE-49270"]),
        ("AE-11111 and AE-22222", ["AE-11111", "AE-22222"]),
        ("AE-22222 AE-11111 ae-22222", ["AE-22222", "AE-11111"]),
    ],
)
def test_extract_valid_codes(subject: str, expected: list[str]) -> None:
    assert extract_shipment_codes(subject) == expected


@pytest.mark.parametrize(
    "subject",
    [
        "AE-1234",
        "AE-123456",
        "XAE-12345",
        "1AE-12345",
        "AE-12345x1".replace("x1", "6"),
        "",
        "TRAINING",
    ],
)
def test_extract_rejects_invalid(subject: str) -> None:
    assert extract_shipment_codes(subject) == []
