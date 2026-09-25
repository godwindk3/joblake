# CareerLink

Source `careerlink` chỉ discovery ngành CNTT - Phần mềm tại
`https://www.careerlink.vn/viec-lam/cntt-phan-mem/19`.
Trang 1 dùng URL gốc; trang 2 trở đi dùng `?page=N`. Không crawl lặp trang 1.

Discovery và detail dùng CloakBrowser, chạy headed trong Xvfb của Airflow.
Browser state lưu riêng tại `data/state/careerlink_browser_state.json`.
Browser dùng `humanize: true`, `geoip: false`, locale `vi-VN` và timezone
`Asia/Ho_Chi_Minh`, tương tự TopCV. Chờ Cloudflare tự hoàn tất tối đa 60 giây.
Discovery nghỉ 10–16 giây/trang, detail nghỉ 7–15 giây/job; discovery tối đa
3 lần thử, detail 2 lần thử với backoff cơ sở 90 giây, trần cơ sở 180 giây
(jitter/Retry-After có thể làm thời gian thực tế dài hơn).
Proxy mặc định tắt; các biến cấu hình riêng dùng tiền tố `CAREERLINK_`.
Discovery chờ `li.job-item a.job-link[href]`, detail chờ `#job-title` trước
khi đọc HTML. Không cần build lại image; task mới đọc YAML được mount.
Đổi transport không đảm bảo khắc phục chặn IP. URL job lấy trong
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
`joblake_serial`. Detail xử lý tối đa 30 URL đủ điều kiện mỗi lần chạy.
Airflow không tự retry task detail; retry URL do state quản lý, vẫn tôn trọng
`next_retry_at`. Chạy lại thủ công để xử lý batch kế tiếp.
Nếu ba URL liên tiếp lỗi tải/validation/storage, detail dừng với trạng thái
`failed` để trả slot; các URL chưa claim vẫn nằm trong queue. URL đã lỗi giữ
retry policy hiện có. Một URL xử lý không lỗi sẽ reset chuỗi lỗi. Ngưỡng này
là `detail.max_consecutive_errors: 3`, không thay đổi các source khác.

Khi website lỗi kéo dài, pause riêng DAG trước khi dừng task đang chạy.
Sau khi xác minh website trả HTML hợp lệ, unpause để tiếp tục retry; không
reset bảng state hay bỏ qua `next_retry_at`. Thay đổi code không cập nhật
tiến trình Python đã chạy, chỉ có hiệu lực khi task khởi động lại.

CareerLink chờ khóa source tối đa 60 giây để tiến trình trước kịp thoát và
nhả khóa. Hết hạn vẫn fail, không cưỡng đoạt khóa hoặc chạy hai phase đồng thời.
Source khác mặc định giữ hành vi fail ngay khi khóa đang được giữ.
Detail lưu bằng chứng lỗi tại `data/state/diagnostics/careerlink/detail`,
giữ tối đa 30 bộ trong 7 ngày theo cleanup khi crawl. Không lưu success thường xuyên.

## Xác minh 2026-09-25

- Run lỗi ngày 23/09 trả HTTP 200 nhưng thiếu `#job-title` trong 30 giây.
  Khi đó chưa bật diagnostics nên không có HTML lỗi để khẳng định chặn mềm,
  redirect hay lỗi render. Không kết luận bị ban IP.
- Probe trong container Airflow, cùng fetcher và bản sao browser state:
  ba URL lỗi 3605644, 3605738, 3027561 đều HTTP 200 và qua validation.
  Bằng chứng tại `data/state/diagnostics/careerlink/probe`.
- Log parse ngày 23/09 lúc 04:54:05 UTC gặp khóa source; detail chỉ nhận SIGTERM
  lúc 04:54:12 UTC. Đây là cuộc đua giữa trạng thái task và tiến trình chưa thoát.
  Log task không đủ xác định ai/cơ chế nào đã chuyển detail sang failed.
- Đã kiểm tra handoff bằng hai session PostgreSQL trên key kiểm thử riêng:
  session sau chỉ vào phase sau khi session trước nhả khóa.
- Chạy pipeline thật trong container: detail run 348 xử lý 3 URL, 0 lỗi;
  parse run 349 xử lý 246 bản ghi, partial=246, rejected=0, failed=0,
  exhausted=0; cả hai phase completed. Partial là chất lượng dữ liệu được
  chấp nhận, không phải lỗi parse. Chưa chứng minh ổn định khi crawl dài.
- 30 unit test thuộc source lock, CareerLink, diagnostics, pipeline và
  fetcher đều pass; DAG import thành công trong Airflow và detail.retries=0.

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
