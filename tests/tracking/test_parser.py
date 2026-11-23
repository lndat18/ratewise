"""Test parser: EmailMessage -> ParsedEmail."""

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage

from conftest import MessageFactory

from falcon.tracking.parser import parse_email, strip_html


def test_parse_basic_fields(make_message: MessageFactory) -> None:
    parsed = parse_email(make_message())
    assert parsed.message_id == "<m1@example.com>"
    assert parsed.subject == "Re: AE-49270 quote"
    assert parsed.from_addr == "alice@example.com"
    assert parsed.to_addrs == ["bob@example.com", "carol@example.com"]
    assert parsed.cc_addrs == ["dan@example.com"]
    assert parsed.sent_at == datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
    assert parsed.body_text.strip() == "hello"
    assert parsed.attachments == []


def test_missing_message_id_uses_content_hash(make_message: MessageFactory) -> None:
    first = parse_email(make_message(message_id=None))
    again = parse_email(make_message(message_id=None))
    other = parse_email(make_message(message_id=None, body="different"))
    assert first.message_id.startswith("sha256:")
    assert first.message_id == again.message_id
    assert first.message_id != other.message_id


def test_broken_date_gives_none(make_message: MessageFactory) -> None:
    assert parse_email(make_message(date="not a date")).sent_at is None


def test_missing_date_gives_none(make_message: MessageFactory) -> None:
    assert parse_email(make_message(date=None)).sent_at is None


def test_naive_date_assumed_utc(make_message: MessageFactory) -> None:
    parsed = parse_email(make_message(date="Mon, 23 Nov 2026 10:00:00 -0000"))
    assert parsed.sent_at is not None
    assert parsed.sent_at.utcoffset() == timedelta(0)


def test_timezone_offset_preserved(make_message: MessageFactory) -> None:
    parsed = parse_email(make_message(date="Mon, 23 Nov 2026 10:00:00 +0700"))
    assert parsed.sent_at == datetime(2026, 11, 23, 10, 0, tzinfo=timezone(timedelta(hours=7)))


def test_html_only_body_is_stripped() -> None:
    msg = EmailMessage()
    msg["Subject"] = "AE-49270"
    msg["Message-ID"] = "<h@x>"
    msg.set_content(
        "<html><style>p{}</style><script>alert(1)</script><p>Hi <b>there</b></p></html>",
        subtype="html",
    )
    body = parse_email(msg).body_text
    assert "Hi there" in body
    assert "<" not in body
    assert "alert" not in body
    assert "p{}" not in body


def test_plain_preferred_over_html() -> None:
    msg = EmailMessage()
    msg["Message-ID"] = "<alt@x>"
    msg.set_content("plain text")
    msg.add_alternative("<p>html text</p>", subtype="html")
    assert parse_email(msg).body_text.strip() == "plain text"


def test_nul_characters_removed() -> None:
    msg = EmailMessage()
    msg["Subject"] = "AE-49270 a\x00b"
    msg["Message-ID"] = "<nul@x>"
    msg.set_content("x\x00y")
    parsed = parse_email(msg)
    assert "\x00" not in parsed.subject
    assert "\x00" not in parsed.body_text


def test_unknown_charset_does_not_crash() -> None:
    raw = (
        b"Subject: AE-49270\r\nMessage-ID: <cs@x>\r\n"
        b"Content-Type: text/plain; charset=x-nonexistent\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\ncaf\xc3\xa9\r\n"
    )
    msg = message_from_bytes(raw, policy=policy.default)
    assert "caf" in parse_email(msg).body_text


def test_attachments_extracted(make_message: MessageFactory) -> None:
    data = b"%PDF-1.4 test"
    parsed = parse_email(make_message(attachments=[("rate.pdf", data)]))
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.filename == "rate.pdf"
    assert att.content_type == "application/pdf"
    assert att.size_bytes == len(data)
    assert att.sha256 == hashlib.sha256(data).hexdigest()
    assert att.content == data
    assert "test" not in parsed.body_text  # attachment không lẫn vào body


def test_strip_html_basic() -> None:
    assert strip_html("<div>a</div><div>b</div>") == "a\nb"
