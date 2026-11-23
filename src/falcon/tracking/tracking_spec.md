# Tracking: đồng bộ email Foxmail (IMAP) vào PostgreSQL, xem theo shipment

Trạng thái: Approved (2026-11-23)

## 1. Mục tiêu & phạm vi

Xây hệ thống đơn giản để **track từng shipment**, trong mỗi shipment có **toàn bộ email** của shipment đó.

- Foxmail chỉ là client. Nguồn dữ liệu là mailbox IONOS đọc qua **IMAP** (`imap.ionos.com:993` SSL, theo tab Server trong Foxmail). Tái dùng `falcon.email.ImapClient` (chỉ đọc, `BODY.PEEK`).
- Một **sync worker** định kỳ kéo mail mới, nhận diện shipment ID, lưu vào **PostgreSQL** cài trên máy này.
- Một **web UI tối giản** (chỉ đọc):
  - Trang danh sách: mỗi hàng là một shipment (vd. `AE-49270`).
  - Bấm vào một hàng: trang chi tiết liệt kê các email của shipment đó (như danh sách mail trong Foxmail).
- Trọng tâm là backend: sync đúng, idempotent, không mất mail. UI chỉ đủ để xem.

Tiêu chí hoàn thành: xem mục 9.

## 2. Không làm (v1)

- Không trích xuất dữ liệu lô hàng (ZIP, trọng lượng...), không lấy giá, không book: thuộc spec khác.
- Không gửi/trả lời mail, không thay đổi mailbox (không đánh dấu đã đọc, không xóa, không di chuyển).
- Không đồng bộ xóa/di chuyển/flag: mail đã lưu thì giữ nguyên (append-only).
- Không tìm shipment ID trong thân thư hoặc nội dung file đính kèm (xem mục 10).
- Không IMAP IDLE, không hàng đợi/Celery, không async.
- Không đăng nhập/phân quyền cho web (chỉ bind `127.0.0.1`), không phân trang, không JS framework.
- Không render HTML của mail (rủi ro XSS/tracking pixel); chỉ hiển thị text.
- Không lưu file `.eml` gốc; không tải lại file đính kèm quá lớn có chính sách riêng.
- Không ORM, không Alembic.

## 3. Công cụ & công nghệ

| Việc | Chọn | Lý do |
| --- | --- | --- |
| DB | PostgreSQL (cài sẵn trên máy), kết nối qua `DATABASE_URL` | Người dùng đã chọn |
| Driver | `psycopg` 3 (`psycopg[binary,pool]`), SQL thuần | Ít bề mặt lỗi hơn ORM cho 5 bảng; sync khớp với `imaplib` đồng bộ. Developer xác nhận wheel hỗ trợ Python 3.14 qua context7/`uv` trước khi chốt |
| Migration | File `migrations/NNN_*.sql` đánh số + bảng `schema_migrations`, chạy bằng `falcon db migrate` | Đủ cho v1, không kéo thêm Alembic |
| Web | `fastapi` + `uvicorn` + `jinja2` (render server, autoescape bật) | Người dùng đã chọn; 2 trang, không build step |
| CLI | `typer` | Theo `coding-convention` |
| Model dữ liệu | `pydantic` v2 | Theo `coding-convention` |
| Parse mail | `email` stdlib (`policy.default`) | Đã dùng trong `ImapClient.fetch` |
| Lưu file đính kèm | Ổ đĩa ngoài repo, `DATA_DIR/attachments/<sha256>` | Người dùng đã chọn; DB chỉ giữ metadata |
| Đồng bộ | Polling theo UID | Người dùng đã chọn; đơn giản, chạy lại an toàn |

Dependency mới cần thêm vào `pyproject.toml`: `psycopg[binary,pool]`, `fastapi`, `uvicorn`, `jinja2`, `typer`, `pydantic`. Dev: `pytest`, `httpx` (test web).

## 4. Cấu hình & cấu trúc code

Biến môi trường (thêm vào `.env.example`; không commit giá trị thật):

| Biến | Ý nghĩa | Mặc định |
| --- | --- | --- |
| `IMAP_HOST/PORT/USER/PASSWORD` | Đã có | — |
| `DATABASE_URL` | vd. `postgresql://user:pass@localhost:5432/falcon` | bắt buộc |
| `DATA_DIR` | Thư mục gốc lưu file đính kèm, **ngoài repo** | `~/falcon_data` |
| `SYNC_FOLDERS` | Danh sách folder IMAP, phân cách bằng dấu phẩy | `INBOX,Sent Items` (xem mục 10) |
| `SYNC_INTERVAL_SECONDS` | Chu kỳ polling | `300` |

Cấu trúc (theo `coding-convention`: mỗi logic một package, chia nhiều module):

```
src/falcon/
  email/client.py          # có sẵn; bổ sung đọc UIDVALIDITY/UIDNEXT khi select (xem mục 6)
  tracking/
    tracking_spec.md
    models.py              # Pydantic: ParsedEmail, ParsedAttachment
    shipment_code.py       # extract_shipment_codes(subject) -> list[str]  (hàm thuần)
    parser.py              # EmailMessage -> ParsedEmail (hàm thuần)
    storage.py             # ghi file đính kèm ra đĩa theo sha256
    repository.py          # toàn bộ SQL: upsert email, shipment, sync_state, truy vấn cho web
    sync.py                # sync_folder / sync_all, nhận MailSource (Protocol) để fake khi test
    migrations/001_init.sql
    web/app.py, templates/{shipments.html,shipment_detail.html}
  cli.py                   # typer: db migrate | sync [--loop] | web
```

`config.py` hiện dùng `dataclass`; phần cấu hình mới viết bằng Pydantic (`DatabaseConfig`, `SyncConfig`) theo convention, không bắt buộc sửa `ImapConfig`.

## 5. Mô hình dữ liệu

Một email có thể xuất hiện ở nhiều folder (Foxmail copy/move) và có thể nhắc nhiều shipment ID → tách bảng nguồn và bảng liên kết.

```sql
shipments(
  id bigserial PK,
  code text UNIQUE NOT NULL,            -- 'AE-49270' (chuẩn hóa in hoa)
  created_at timestamptz NOT NULL DEFAULT now()
)

emails(
  id bigserial PK,
  message_id text UNIQUE NOT NULL,      -- header Message-ID; thiếu thì 'sha256:<hash nội dung>'
  subject text NOT NULL DEFAULT '',
  from_addr text NOT NULL DEFAULT '',
  to_addrs text[] NOT NULL DEFAULT '{}',
  cc_addrs text[] NOT NULL DEFAULT '{}',
  sent_at timestamptz,                  -- NULL nếu header Date hỏng
  body_text text NOT NULL DEFAULT '',   -- ưu tiên text/plain; chỉ có HTML thì strip tag
  created_at timestamptz NOT NULL DEFAULT now()
)

email_sources(                          -- email nằm ở folder/UID nào
  email_id bigint FK, folder text, uidvalidity bigint, uid bigint,
  UNIQUE(folder, uidvalidity, uid)
)

shipment_emails(
  shipment_id bigint FK, email_id bigint FK,
  PRIMARY KEY(shipment_id, email_id)
)

attachments(
  id bigserial PK, email_id bigint FK,
  filename text, content_type text, size_bytes bigint,
  sha256 text NOT NULL                  -- đường dẫn = DATA_DIR/attachments/<sha256>
)

sync_state(
  folder text PRIMARY KEY, uidvalidity bigint NOT NULL, last_uid bigint NOT NULL
)

schema_migrations(version int PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())
```

Index: `shipment_emails(email_id)`, `emails(sent_at)`, `attachments(email_id)`.

Bên cạnh đó: file đính kèm trùng nội dung (cùng sha256) dùng chung một file trên đĩa.

## 6. Luồng sync

`falcon sync` chạy một lượt; `falcon sync --loop` lặp mỗi `SYNC_INTERVAL_SECONDS`.

1. Lấy `pg_try_advisory_lock`; không lấy được (đã có worker khác chạy) thì thoát êm.
2. Mở một kết nối IMAP. Với từng folder trong `SYNC_FOLDERS`:
   1. `SELECT` readonly, đọc `UIDVALIDITY` và `UIDNEXT`.
   2. So `UIDVALIDITY` với `sync_state`. Khác hoặc chưa có → coi `last_uid = 0` (quét lại từ đầu). An toàn vì ingest idempotent (dedupe theo `message_id`).
   3. `UID SEARCH UID {last_uid+1}:* SUBJECT "AE-"`. Lọc bỏ UID `<= last_uid` (IMAP luôn trả ít nhất mail cuối với cú pháp `N:*`).
   4. Với mỗi UID: `fetch` → `parser` → `extract_shipment_codes(subject)`. Không có code hợp lệ thì bỏ qua (SEARCH chỉ là bộ lọc thô, substring).
   5. Ghi DB trong **một transaction mỗi email**: upsert `emails` theo `message_id` (`ON CONFLICT DO NOTHING` rồi lấy id), insert `email_sources`, upsert `shipments`, insert `shipment_emails`, lưu file đính kèm và insert `attachments` (chỉ khi email mới).
   6. Sau khi cả folder xử lý xong: `sync_state.last_uid = UIDNEXT - 1` đã đọc ở bước (i), trước khi SEARCH. Mail đến giữa chừng sẽ được lấy ở lượt sau.
3. Nhả advisory lock, đóng kết nối.

Nhận diện shipment ID:

- Regex `(?<![A-Za-z0-9])AE-\d{5}(?!\d)`, không phân biệt hoa/thường, lưu dạng in hoa. Không khớp `AE-1234`, `AE-123456`, `XAE-12345`.
- Subject chứa nhiều ID → mail thuộc tất cả các shipment đó. Giữ nguyên `Re:`/`Fw:` vì ID vẫn nằm trong subject.

Ghi file đính kèm: ghi ra file tạm rồi `rename` sang `<sha256>` (atomic); đã tồn tại thì bỏ qua. Tên file người gửi chỉ lưu trong DB, **không bao giờ** dùng để dựng đường dẫn.

## 7. Web UI

Chỉ đọc, bind `127.0.0.1`, hàm route đồng bộ (`def`, không `async`). Lệnh `falcon web`.

- `GET /`: bảng shipment, sắp theo mail mới nhất giảm dần. Cột: code, số email, thời điểm email mới nhất, subject email mới nhất. Ô lọc `?q=` khớp một phần `code`.
- `GET /shipments/{code}`: thông tin shipment + danh sách email theo `sent_at` tăng dần (`NULLS LAST, id`). Mỗi email: ngày, from, to, subject; bấm mở `<details>` để xem `body_text`; danh sách file đính kèm có link tải. Code không tồn tại → 404.
- `GET /attachments/{id}`: `FileResponse` từ `DATA_DIR/attachments/<sha256>` với `Content-Disposition: attachment` và tên file đã làm sạch. Không tồn tại → 404.
- Jinja2 autoescape bật; `body_text` luôn escape, hiển thị `white-space: pre-wrap`.

## 8. Lỗi & trường hợp biên (phần lõi)

- **Chạy lại / chạy chồng**: sync 2 lần liên tiếp không tạo bản ghi trùng (UNIQUE `message_id`, `(folder, uidvalidity, uid)`, `(shipment_id, email_id)`). Hai worker không chạy song song nhờ advisory lock.
- **Cùng mail ở 2 folder** (hoặc bị move): một dòng `emails`, hai dòng `email_sources`.
- **`UIDVALIDITY` đổi**: quét lại folder từ đầu, không tạo trùng.
- **Một email lỗi parse/ghi** (hỏng MIME, lỗi DB): rollback transaction của email đó, log lỗi kèm folder + UID (không log nội dung mail), dừng folder đó, **không** nâng `last_uid`, các folder khác vẫn chạy. Lượt sau thử lại. Hạn chế đã biết: một mail "độc" sẽ chặn folder cho tới khi sửa; chấp nhận ở v1.
- **IMAP lỗi kết nối/đăng nhập**: lượt sync fail, thoát mã khác 0; ở chế độ `--loop` log rồi thử lại ở chu kỳ sau. Không để lộ mật khẩu trong log.
- **Mail thiếu `Message-ID`**: dùng `sha256:<hash nội dung>` để vẫn dedupe được.
- **Header Date hỏng**: `sent_at = NULL`, vẫn lưu.
- **Charset lạ / không có text/plain**: dùng `policy.default`; chỉ có HTML thì strip tag bằng `html.parser`; không crash.
- **Mail không có ID hợp lệ trong subject** dù SEARCH khớp: bỏ qua, không lưu.
- **Đĩa/DB đầy**: coi như lỗi email (rollback, dừng folder).
- **Bảo mật**: `DATABASE_URL`, mật khẩu IMAP chỉ ở `.env`; `DATA_DIR` ngoài repo; email thật không gửi ra dịch vụ ngoài (theo CLAUDE.md).

Phần ngoài lõi (UI trình bày, thứ tự cột, phân trang): ghi "Không làm", không mô tả.

## 9. Tiêu chí hoàn thành

- `falcon db migrate` tạo đủ bảng; chạy lại không lỗi.
- `falcon sync` với mailbox thật kéo được các mail có `AE-xxxxx` trong subject (vd. `AE-49270`); chạy lần hai không tăng số dòng.
- `falcon web`: `/` liệt kê shipment; bấm vào `AE-49270` thấy đủ email của shipment, mở được thân thư và tải được file đính kèm.
- Mailbox không bị thay đổi (không mail nào đổi trạng thái đã đọc).
- Test: unit cho `shipment_code`, `parser`; `sync` với `MailSource` giả (fake) kiểm tra idempotent, `UIDVALIDITY` đổi, mail ở 2 folder, mail lỗi không nâng cursor; integration thật với Postgres đánh marker `integration` (job CI cho Postgres do người dùng làm tay trong PR `chore` riêng); web test bằng `httpx`/`TestClient`.

## 10. Giả định cần người dùng xác nhận

1. **Folder cần sync**: mặc định `INBOX` + thư đã gửi. Chạy `scripts/test_imap.py` để lấy tên folder IMAP thật (Foxmail có folder `AE`, `AES`, `NOTI EXFREIGHT`...; chúng có thể là rule cục bộ của Foxmail chứ không tồn tại trên server).
2. **ID chỉ nằm trong subject**: mail có `AE-xxxxx` chỉ trong thân thư sẽ bị bỏ sót. Nếu cần, thêm `OR SUBJECT "AE-" BODY "AE-"` ở bước 6.2.iii và quét thân thư (chậm hơn, nhiều false positive hơn).
3. **Mail không có ID** (vd. "TRAINING VICTOR 2026") không được lưu vì không thuộc shipment nào.
