# Ratewise: spec v0

## Vấn đề

Tìm trucker rẻ nhất đang phải nhập tay từng portal, rất mất thời gian.

## Mục tiêu

Một cổng vào duy nhất (form): nhập thông tin lô hàng một lần, hệ thống map sang từng portal để lấy giá.

## Portal và dịch vụ

| Dịch vụ     | Portal                             |
| ------------- | ---------------------------------- |
| LTL           | Priority1, ShipRite, myUnishippers |
| Small package | SpeedShip                          |

Form chia theo dịch vụ: LTL và small package có schema riêng, dùng chung phần field chung.

## Cấu trúc

```
src/ratewise/
  form/      # schema cổng vào (model, validation); không chứa code giao diện
  mapping/   # canonical -> field của từng portal (hàm thuần)
  adapter/   # thao tác thực tế với portal (đăng nhập, lấy giá)
```

- Giữ tên `form` vì sẽ có UI form cho team nhập.
- UI nằm ngoài core (`web/`), giao tiếp qua một lớp API.

## Thứ tự làm

1. `form/`  2. `mapping/` + `adapter/` cho một portal  3. các portal còn lại + chạy song song  4. API, rồi UI

## Chưa chốt

- Danh sách field chính thức của form (Lớp chung, Lớp LTL, Lớp small package).
- Cách lấy giá: browser automation hay gọi API nội bộ của portal.
- Công nghệ UI.
