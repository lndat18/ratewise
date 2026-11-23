# CLAUDE.md

## Mục tiêu dự án (falcon)

Agent giải quyết bài toán **book trucker** cho Baylink Logistics. Luồng chính:

1. **Đọc email** từ Foxmail (mail của team) để lấy yêu cầu theo từng lô hàng.
2. **Trích xuất** thông tin lô hàng cần thiết (ZIP gửi/nhận, ngày gửi, handling unit, số lượng, trọng lượng, kích thước, class, NMFC, accessorial, insurance...).
3. **Lấy giá** từ 5 broker/portal.
4. **So sánh và gợi ý** trucker có giá tốt nhất cho user.
5. Nếu user đồng ý, agent **book luôn** trên portal tương ứng.

## Quyết định đã chốt

| Chủ đề | Quyết định |
|---|---|
| Đọc email | **IMAP trực tiếp** vào mail server (không điều khiển GUI Foxmail). Foxmail chỉ là client. Host/port/giao thức xem tab Server trong Foxmail, Option > Account. |
| Phạm vi email | Hệ thống **lọc sẵn theo shipment ID** (ví dụ `AE-49270`). Agent chỉ xử lý **lô hàng được yêu cầu**, không quét toàn bộ hộp thư. |
| Giao diện | **Chat/CLI trong terminal**: hiển thị bảng so giá và hỏi user có book không. |
| Book | **Hoàn tất tự động sau khi user xác nhận 1 lần.** Ngay trước khi submit phải lấy lại giá; nếu lệch so với giá đã gợi ý thì **dừng và hỏi lại**. |

## Các portal (5 broker)

| Portal | URL | Ghi chú |
|---|---|---|
| Priority1 | https://dashboard.priority1.com/ltl/quotes/create/41930 | LTL (41930 là ID gắn với tài khoản) |
| ShipRite | https://ondemand.shiprite.com/quick-quote/new | Hàng quá khổ/quá nặng có thể không có giá tự động, phải báo giá qua email |
| Exfreight (Flipstone) | https://exfreight.flipstone.com/menu/customer | Vào từ menu customer |
| myUnishippers | https://www.myunishippers.com/ship/ltl | LTL |
| SpeedShip (Worldwide Express) | https://www.speedship.com/ship/ltl | Lần này dùng nhánh **LTL**, khác bản spec cũ (small package) |

## Nguyên tắc bắt buộc

- **Book là hành động có tiền, khó hoàn tác.** Không bao giờ book khi chưa có xác nhận rõ ràng của user cho đúng lô hàng, trucker và mức giá đó.
- Chỉ xử lý đúng shipment ID mà user yêu cầu. Không tự suy ra lô hàng khác từ hộp thư.
- Nếu email thiếu thông tin bắt buộc (ZIP, trọng lượng, kích thước, class...), **hỏi user bổ sung**, không tự đoán.
- Chạy 5 portal song song. Một portal lỗi hoặc không có giá không được làm hỏng cả lượt so giá. Báo rõ portal nào thiếu giá và lý do.
- So sánh giá phải nêu rõ: giá, transit time, carrier, và các phụ phí (accessorial) đã tính vào.
- **Không commit bí mật.** Mật khẩu email, tài khoản portal, cookie/session phải nằm ngoài repo (`.env` hoặc secret manager, đã có trong `.gitignore`). Không ghi chúng vào log hay vào CLAUDE.md.
- Không dán nội dung email thật (tên khách, mã đơn) vào dịch vụ bên ngoài ngoài các portal cần để báo giá/book.

## Kiến trúc dự kiến

```
src/falcon/
  tracking/  # (đã có) sync email IMAP -> PostgreSQL, web xem theo shipment: xem tracking/tracking_spec.md
  email/     # IMAP: tìm mail theo shipment ID, tải nội dung + file đính kèm
  extract/   # trích xuất email -> QuoteRequest (LLM + validation)
  form/      # schema chuẩn (QuoteRequest, Item, Location, Accessorials, Insurance)
  mapping/   # canonical -> field của từng portal (hàm thuần)
  adapter/   # mỗi portal 1 adapter: login, get_quote(), book()
  compare/   # so sánh, xếp hạng, đề xuất trucker
  cli/       # chat terminal: hiển thị bảng giá, xin xác nhận, gọi book
```

Giao diện adapter thống nhất cho mọi portal: `get_quote(QuoteRequest) -> list[Quote]` và `book(Quote) -> Booking`.
Schema chuẩn: `Shipment` (ngày gửi, origin, destination) + `items[]` + `accessorials` (pickup/delivery) + `insurance`. Spec form cũ có trong git history (`docs/spec_form.md`, `docs/spec_get_data.md`, commit `195862a`).

## Cách lấy giá và book (ưu tiên theo thứ tự)

1. API chính thức của portal nếu được cấp.
2. Playwright + bắt response JSON của API ngầm.
3. Playwright đọc DOM nếu không có JSON sạch.

Book thực hiện bằng cùng cơ chế đã đăng nhập của adapter đó.

## Câu hỏi còn mở (chưa chốt, cần xác minh trước khi code phần liên quan)

- **Mail server**: IMAP, POP3 hay Exchange? Host/port? Có cần app password không? (xem tab Server trong Foxmail)
- **Định dạng email**: thông tin lô hàng nằm trong thân thư, file đính kèm (PDF/Excel) hay cả hai? Cần vài email mẫu (đã ẩn thông tin khách) để thiết kế bước trích xuất.
- **Shipment ID**: dạng `AE-xxxxx` có khớp tiêu đề thư hay thân thư? Ai/phần nào của hệ thống lọc ra ID và đưa cho agent?
- **Tài khoản 5 portal**: có tài khoản đăng nhập đủ cả 5 không? Có 2FA/CAPTCHA không? Có API chính thức không?
- **Book**: portal nào có bước thanh toán/xác nhận thêm? Có hạn mức giá tối đa agent được book không? Booking xong có cần gửi mail/ghi lại cho khách không?
- **Chạy ở đâu**: máy cá nhân hay server chạy không người trông? Thời gian chờ chấp nhận được cho mỗi lần báo giá?
- **Tiêu chí "tốt nhất"**: chỉ giá thấp nhất, hay có cân nhắc transit time và độ tin cậy carrier?

## Môi trường

- Python (xem `.python-version`), quản lý bằng `uv` (`pyproject.toml`, `uv.lock`).
- Mã nguồn trong `src/falcon/`.
