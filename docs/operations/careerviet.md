# CareerViet

Source `careerviet` chỉ discovery ngành CNTT - Phần mềm (`c1`):
`https://careerviet.vn/viec-lam/cntt-phan-mem-c1-trang-N-vi.html`.
Trang không có `trang-N` tương ứng trang 1; config chỉ chạy một target,
không crawl hai lần trang đầu hoặc mở rộng sang ngành khác.

## Fetch và phân trang

Discovery/detail dùng `requests` với `user_agent: JobLake/0.1`.
Khi kiểm tra, server đóng kết nối với User-Agent mặc định python-requests;
User-Agent cấu hình ở trên trả HTTP 200. Không cần đăng nhập hoặc browser.

Adapter đọc `totalJobs` và `limit` từ chuỗi JSON của React Flight trong HTML,
không thực thi JavaScript. Tổng trang là ceil(totalJobs / limit), không lấy
nút cuối đang hiển thị trong cửa sổ phân trang. Metadata mất hoặc không đúng
ngành `1` thì báo lỗi phát hiện phân trang; không tự coi 5 là trang cuối.
Giới hạn tự động 200 trang. URL discovery chỉ lấy trong vùng kết quả,
chuẩn hóa bỏ query/fragment và loại trùng.

## Detail và parser

Kiểm tra HTTP, host, đường dẫn, mã job ở URL và JSON-LD; yêu cầu tiêu đề và
mô tả/yêu cầu thực sự có trong HTML. Tên công ty không bắt buộc là link,
có fallback từ `hiringOrganization.name`. Trang redirect sang job khác,
trang lỗi, đăng nhập hoặc chỉ có skeleton không được lưu làm raw hợp lệ.

Parser tách mô tả và yêu cầu từ từng section, lấy phúc lợi, ngành nghề,
địa điểm, lương, hình thức, kinh nghiệm từ HTML; kỹ năng và ngày đăng lấy
từ JSON-LD khi có. Ngày cập nhật được giữ trong source_payload, không dùng
thay ngày đăng. Ngành nghề vào `categories_raw`; không tự suy diễn
`domains_raw` hoặc trích kỹ năng từ văn bản tự do. Mẫu kiểm tra đạt `partial`
do thiếu lĩnh vực và một số tin không có trường kỹ năng riêng.

## Chạy

Config dùng MinIO/PostgreSQL hiện tại; không cần migration riêng.

```powershell
python -m joblake.main --config configs/careerviet.yaml --phase discovery --strict
python -m joblake.main --config configs/careerviet.yaml --phase detail --strict
python -m joblake.main --config configs/careerviet.yaml --phase parse --strict
```

DAG `joblake_careerviet`: mặc định paused, chạy thủ công, pool
`joblake_serial`, luồng discovery → detail → parse. Detail mặc định xử lý
toàn bộ URL đủ điều kiện (`max_jobs_per_run: null`).

## Xác minh 2026-09-18

Sau lượt chạy toàn bộ, phát hiện 30 lần validation lỗi trên 16 URL duy nhất
(14 URL được thử lại sau thời gian chờ). Nguyên nhân là các template riêng
của nhà tuyển dụng: title h2/h1 không có class, section h3, tiêu đề section
nằm trong `title-icon`, hoặc không dùng `.apply-now-banner`/`.job-detail-content`.
Validator v2 và parser 1.0.1 dùng chung bộ đọc section, hỗ trợ các dạng này
và fallback trường phụ từ JSON-LD. Vẫn bắt buộc có tiêu đề và mô tả/yêu cầu
được render, đồng thời giữ kiểm tra mã job; không chấp nhận JSON-LD-only shell.
Đã tải lại và xác minh cả 16 URL: validation thành công và parse `partial`.
Bản sửa chưa chạy lại ingestion vào database.

- Fetcher thật chạy trang 1–3: 150 URL duy nhất.
- Metadata: 685 tin, 50 tin/trang, 14 trang; fetch trang 14 được 35 tin.
- Ba detail người dùng cung cấp và ba tin lấy thêm từ listing: cả sáu qua
  validation và parser, chất lượng `partial` được chấp nhận.
- Fixtures giữ các vùng HTML phục vụ extraction và metadata phân trang
  được rút gọn; không cần network khi chạy test.
- Smoke test không ghi PostgreSQL/MinIO hoặc kích hoạt DAG. Chưa chạy
  ingestion toàn bộ hay kiểm tra import DAG trong Airflow thật.

```powershell
python -m unittest discover -s tests -p test_careerviet.py
```
