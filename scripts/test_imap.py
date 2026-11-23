"""Kiểm tra kết nối IMAP.

    uv run python scripts/test_imap.py            # chỉ liệt kê folder
    uv run python scripts/test_imap.py AE-49270   # tìm thư theo shipment ID
"""

import sys

from falcon.config import ImapConfig
from falcon.email import ImapClient


def main() -> None:
    cfg = ImapConfig.from_env()
    print(f"Kết nối {cfg.host}:{cfg.port} bằng {cfg.user} ...")
    with ImapClient(cfg) as client:
        print("Đăng nhập OK. Folders:")
        folders = client.list_folders()
        for f in folders:
            print("  -", f)

        if len(sys.argv) > 1:
            shipment_id = sys.argv[1]
            # Tìm theo tiêu đề; nếu ID nằm trong thân thư thì đổi SUBJECT -> TEXT
            uids = client.search("INBOX", "SUBJECT", f'"{shipment_id}"')
            print(f"\nINBOX: {len(uids)} thư khớp {shipment_id!r} trong tiêu đề")
            for uid in uids:
                msg = client.fetch(uid)
                print(f"  UID {uid.decode()}: {msg['Date']} | {msg['From']} | {msg['Subject']}")


if __name__ == "__main__":
    main()
