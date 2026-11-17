# CLAUDE.md

## Mục tiêu dự án (ratewise)

Công cụ so sánh giá vận chuyển (freight rate shopping). Hiện tại người dùng phải nhập cùng một lô hàng vào nhiều cổng báo giá khác nhau để so giá. Ratewise giải quyết việc đó bằng 3 bước:

1. **Nhập thông tin lô hàng một lần** (form chuẩn hoá): ZIP/địa chỉ gửi và nhận, ngày gửi, handling unit, số lượng, trọng lượng, kích thước (L/W/H), class, NMFC, dịch vụ phụ (accessorial)...
2. **Ánh xạ (map) các trường** sang từng cổng, vì mỗi cổng gọi cùng một thứ bằng tên khác nhau.
   - Ví dụ: "Handling Unit" và "Freight Type"; "Lift Gate Pickup" và "Liftgate Pickup".
3. **Tự động điền và lấy giá** từ các cổng, rồi **so sánh giá trên một màn hình**.

## Các cổng cần hỗ trợ

| Cổng | URL | Loại |
|---|---|---|
| Priority1 | dashboard.priority1.com/ltl/quotes/create | LTL |
| ShipRite (CTS) | ondemand.shiprite.com/quick-quote/new | LTL/Air |
| Exfreight (Expresso/Flipstone) | exfreight.flipstone.com/ratings | LTL/quốc tế |
| myUnishippers | myunishippers.com/ship/ltl | LTL |
| Worldwide Express (SpeedShip) | speedship.com/ship/small-package | Small package |

## Trạng thái

- Repo mới khởi tạo, chưa có code.
- Chưa quyết định: cách tự động hoá (browser automation / API / hybrid), dạng ứng dụng (web app, extension, script cục bộ), thứ tự ưu tiên cổng.
