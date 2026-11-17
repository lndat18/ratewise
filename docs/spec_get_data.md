# Spec: Các giải pháp lấy dữ liệu giá (rate data)

Giả định: input lô hàng đã được chuẩn hoá và map đúng sang từng cổng (xem [CLAUDE.md](../CLAUDE.md)). Tài liệu này mô tả các cách lấy giá trả về từ mỗi cổng.

## 1. API chính thức của nhà cung cấp

- Priority1, Unishippers/Worldwide Express (Speedship) và Exfreight/Flipstone là nền tảng lớn, có khả năng có API rating cho khách hàng.
- Cách làm: xin API key hoặc credentials, gọi REST/SOAP và nhận JSON.
- Ưu điểm: nhanh, ổn định, không vỡ khi giao diện đổi.
- Nhược điểm: phải được cấp quyền, có thể mất phí hoặc cần account manager duyệt.
- **Nên làm đầu tiên:** hỏi từng nhà cung cấp xem có API rating không.

## 2. Gọi lại API ngầm của trang web (reverse-engineer)

- Các cổng là web app hiện đại (SPA). Khi bấm "Get Rates", trình duyệt gọi một API nội bộ và nhận JSON.
- Cách làm: mở DevTools → tab Network → bấm Get Rates → xem request/response → viết code gọi lại request đó với token đăng nhập.
- Ưu điểm: nhanh gần như API thật, không cần dựng trình duyệt.
- Nhược điểm: không có tài liệu, có thể đổi bất cứ lúc nào, token hết hạn, có thể vi phạm điều khoản sử dụng.

## 3. Browser automation (Playwright) đọc DOM

- Playwright (thư viện của Microsoft) điều khiển trình duyệt: điền form như người thật rồi đọc bảng giá trên màn hình.
- Ưu điểm: cổng nào cũng làm được, kể cả cổng không có API. Có thể lưu phiên đăng nhập và chạy nhiều cổng song song.
- Nhược điểm: chậm, dễ vỡ khi giao diện đổi, cần xử lý đăng nhập, CAPTCHA, 2FA.

## 4. Kết hợp: Playwright + bắt response mạng

- Playwright lo đăng nhập, điền form và bấm nút. Thay vì đọc DOM thì chặn response JSON của API ngầm (cách 2).
- Ưu điểm: dữ liệu sạch hơn đọc HTML. Playwright lo cookie và token.
- Thường là hướng thực dụng nhất khi không có API chính thức.

## 5. Browser extension

- Extension chạy trong trình duyệt đã đăng nhập sẵn.
- Ưu điểm: dùng luôn phiên hiện có, không cần xử lý login, ít bị chặn như bot.
- Nhược điểm: phải mở trình duyệt thật, khó chạy tự động không người trông, mỗi cổng cần một content script.

## 6. Giải pháp phụ trợ

- **Báo giá thủ công qua email:** với hàng quá khổ hoặc quá nặng thì không có giá tự động (ví dụ ShipRite ghi cần email TLquotes@...).
- **API gộp của bên trung gian:** một số broker/nền tảng (như Freightos, Freightview, project44) cung cấp một API cho nhiều carrier, có thể thay thế vài cổng.

## So sánh nhanh

| Cách | Tốc độ | Độ ổn định | Công sức | Rủi ro |
|---|---|---|---|---|
| 1. API chính thức | Nhanh | Cao | Thấp | Cần cấp quyền |
| 2. API ngầm | Nhanh | Trung bình | Trung bình | Đổi không báo, điều khoản |
| 3. Playwright (DOM) | Chậm | Thấp | Cao | Vỡ khi UI đổi, CAPTCHA |
| 4. Playwright + bắt response | Trung bình | Trung bình | Trung bình | Như trên |
| 5. Extension | Trung bình | Trung bình | Cao | Cần trình duyệt mở |

## Đề xuất (theo từng lớp cho mỗi cổng)

1. Hỏi nhà cung cấp có API không, nếu có thì dùng.
2. Nếu không, thử cách 4 (Playwright + bắt response JSON).
3. Nếu không có JSON sạch, mới đọc DOM (cách 3).

## Việc cần làm tiếp

- Với từng cổng, mở DevTools → Network, bấm Get Rates, lưu request/response (đã xoá token) để đánh giá khả năng dùng cách 2 hoặc 4.
- Xác nhận các điểm còn thiếu:
  - Có tài khoản đăng nhập chính thức ở cả 5 cổng không, và có bật 2FA không?
  - Cần chạy tự động không người trông (server) hay chỉ trên máy cá nhân?
  - Thời gian chờ chấp nhận được cho mỗi lần báo giá (5s, 30s, 1 phút)?
