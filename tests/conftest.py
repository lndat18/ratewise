"""Fixture dùng chung: dựng email giả và nguồn mail/repository giả (không cần IMAP/DB)."""

from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formatdate

import pytest

MessageFactory = Callable[..., EmailMessage]


@pytest.fixture
def make_message() -> MessageFactory:
    """Trả hàm dựng `EmailMessage` với các header tùy chọn."""

    def _make(
        subject: str = "Re: AE-49270 quote",
        message_id: str | None = "<m1@example.com>",
        body: str | None = "hello",
        date: str | None = "Mon, 23 Nov 2026 10:00:00 +0000",
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = "Alice <alice@example.com>"
        msg["To"] = "bob@example.com, Carol <carol@example.com>"
        msg["Cc"] = "dan@example.com"
        if message_id is not None:
            msg["Message-ID"] = message_id
        if date is not None:
            msg["Date"] = date
        else:
            msg["Date"] = formatdate()
            del msg["Date"]
        if body is not None:
            msg.set_content(body)
        for filename, data in attachments or []:
            msg.add_attachment(data, maintype="application", subtype="pdf", filename=filename)
        return msg

    return _make
