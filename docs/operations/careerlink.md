# CareerLink

Source `careerlink` chỉ discovery ngành CNTT - Phần mềm tại
`https://www.careerlink.vn/viec-lam/cntt-phan-mem/19`.
Trang 1 dùng URL gốc; trang 2 trở đi dùng `?page=N`. Không crawl lặp trang 1.

Discovery và detail dùng CloakBrowser, chạy headed trong Xvfb của Airflow.
Browser state lưu riêng tại `data/state/careerlink_browser_state.json`.
Browser dùng `humanize: true`, `geoip: false`, locale `vi-VN` và timezone
`Asia/Ho_Chi_Minh`, tương tự TopCV. Chờ Cloudflare tự hoàn tất tối đa 60 giây.
Discovery nghỉ 10–16 giây/trang, detail nghỉ 7–15 giây/job; cả hai retry tối đa
3 lần với backoff cơ sở 90 giây, trần 180 giây (có jitter/Retry-After).
Proxy mặc định tắt; các biến cấu hình riêng dùng tiền tố `CAREERLINK_`.
Discovery chờ `li.job-item a.job-link[href]`, detail chờ `#job-title` trước
khi đọc HTML. Không cần build lại image; task mới đọc YAML được mount.
Đổi transport không đảm bảo khắc phục chặn IP; chưa xác minh crawl live
với cấu hình browser này. URL job lấy trong
`li.job-item a.job-link`; bỏ query `source=site` và fragment, loại trùng
theo ID trong từng trang. Tổng trang đọc từ pagination, có link trang cuối
(ngày kiểm tra: 9). Nếu thiếu pagination thì báo lỗi phát hiện phân trang;
giới hạn tự động 200 trang.

Validator đối chiếu ID request/final URL/JSON-LD, host, HTTP status và
nội dung thực tế. Title phải có tại `#job-title`, công ty có trong JSON-LD,
mô tả hoặc yêu cầu phải có phần nội dung HTML; không nhận shell chỉ có
JSON-LD. Không bắt buộc link hồ sơ công ty.

Parser tách mô tả, yêu cầu, phúc lợi từ các section riêng; lương và kinh
nghiệm/hình thức từ HTML; ngành nghề, địa điểm và ngày đăng/hết hạn từ
JSON-LD. `domains_raw`, kỹ năng có cấu trúc và phúc lợi để trống khi không
có dữ liệu riêng đáng tin cậy. Phần “Kinh nghiệm / Kỹ năng chi tiết” được
giữ trong `requirements_text`, không tự đoán danh sách kỹ năng.

## Chạy

Config dùng MinIO/PostgreSQL hiện tại; không cần migration riêng:

```powershell
python -m joblake.main --config configs/careerlink.yaml --phase discovery --strict
python -m joblake.main --config configs/careerlink.yaml --phase detail --strict
python -m joblake.main --config configs/careerlink.yaml --phase parse --strict
```

DAG `joblake_careerlink` mặc định paused, chỉ chạy thủ công, pool
`joblake_serial`. Detail mặc định xử lý mọi URL đủ điều kiện (`null`).
Nếu ba URL liên tiếp lỗi tải/validation/storage, detail dừng với trạng thái
`failed` để trả slot; các URL chưa claim vẫn nằm trong queue. URL đã lỗi giữ
retry policy hiện có. Một URL xử lý không lỗi sẽ reset chuỗi lỗi. Ngưỡng này
là `detail.max_consecutive_errors: 3`, không thay đổi các source khác.

Khi website lỗi kéo dài, pause riêng DAG trước khi dừng task đang chạy.
Sau khi xác minh website trả HTML hợp lệ, unpause để tiếp tục retry; không
reset bảng state hay bỏ qua `next_retry_at`. Thay đổi code không cập nhật
tiến trình Python đã chạy, chỉ có hiệu lực khi task khởi động lại.

## Xác minh 2026-09-19

- Fetcher thật duyệt 9 trang, nhận 408 URL duy nhất.
- Bảy detail khác nhau, gồm ba URL người dùng đưa và tin ở nhiều trang:
  tất cả validation thành công, chất lượng `partial` được chấp nhận.
- Test offline dùng các vùng HTML thật được rút gọn, kiểm tra phân trang,
  URL theo dõi, phạm vi listing, dữ liệu thiếu, sai ID và redirect.
- Smoke test không ghi PostgreSQL/MinIO, không kích hoạt DAG. DAG chỉ được
  kiểm tra cú pháp, chưa kiểm tra import trong Airflow thật.

```powershell
python -m unittest discover -s tests -p test_careerlink.py
```
