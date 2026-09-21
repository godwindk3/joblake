# JobsGO

Source `jobsgo` chỉ discovery danh sách Công nghệ thông tin. Dùng một target
`https://jobsgo.vn/nganh-nghe.html`, giữ `slug=viec-lam-cong-nghe-thong-tin`
và tăng `page` từ 1. Không crawl thêm URL landing để tránh lặp trang đầu.

Discovery và detail dùng requests với User-Agent `JobLake/0.1`.
Các mẫu public không cần đăng nhập. Curl với User-Agent mặc định trả trang
blocked trong lần kiểm tra; cần giữ cấu hình User-Agent đã kiểm chứng.

Thanh pagination chỉ hiện một cửa sổ 5 trang, không phải trang cuối.
Adapter lấy tổng tin từ heading `Tuyển dụng N việc làm` và chia cho kích
thước trang 50 tin đã kiểm chứng, làm tròn lên. Nếu website đổi kích thước
trang hoặc cấu trúc heading, phải cập nhật adapter. Thiếu heading/pagination
thì không đoán số trang; giới hạn tự động 200 trang.

URL chỉ lấy từ `.job-list .job-title a`, kiểm tra host và dạng
`/viec-lam/<slug>-<id>.html`; bỏ tracking query/fragment, loại trùng ID
trong trang. Pipeline loại trùng URL giữa các trang.

Validator kiểm tra status/host, ID của request/final/canonical URL,
title thực tế, công ty trong JSON-LD/HTML và mô tả HTML. Trang lỗi hoặc shell
chỉ có JSON-LD không được nhận. ID job lấy từ URL, không dùng ID công ty.

Parser tách mô tả, yêu cầu và phúc lợi từ các section HTML; lấy lương,
kinh nghiệm và hình thức từ thông tin hiển thị. JSON-LD cung cấp công ty,
ngành nghề, địa điểm và ngày đăng/hết hạn. Trường tùy chọn thiếu dữ liệu
để trống và ghi nhận `partial`, không suy diễn kỹ năng từ mô tả.

Tin JobsGO Recruit có thể không có JobPosting JSON-LD. Với mẫu này,
ưu tiên công ty trong khối “Tin tuyển dụng từ công ty” thay vì tên đơn vị
đăng hộ; đọc ngành nghề, địa điểm và ngày tháng từ HTML.

## Chạy

```powershell
python -m joblake.main --config configs/jobsgo.yaml --phase discovery --strict
python -m joblake.main --config configs/jobsgo.yaml --phase detail --strict
python -m joblake.main --config configs/jobsgo.yaml --phase parse --strict
```

Config dùng MinIO/PostgreSQL hiện tại, không cần migration riêng.
DAG `joblake_jobsgo` mặc định paused, chạy thủ công, pool `joblake_serial`.
Detail/parse không giới hạn số job mỗi lượt (`null`).

## Kiểm tra

```powershell
python -m unittest discover -s tests -p test_jobsgo.py
```

Fixture rút gọn từ HTML thật: trang 1, 2, 30 và ba detail người dùng cung cấp.
Test kiểm tra phân trang, query `slug`, phạm vi listing, URL tracking,
dữ liệu parse, redirect sai ID, trang blocked và thiếu nội dung thực tế.
Smoke test chỉ lưu file tạm, không ghi PostgreSQL/MinIO hay kích hoạt DAG.
DAG được kiểm tra cú pháp; chưa import/chạy trong Airflow thật.

Kết quả ngày 2026-09-19: fetcher thật duyệt 30 trang, thu 1.485 URL duy nhất.
Tám detail lấy mẫu gồm ba URL người dùng cung cấp và tin ở nhiều trang.
Sau khi bổ sung mẫu Recruit, cả tám HTML đã fetch đều validate/parse đạt
`partial` (thiếu domains/skills riêng). Bộ test: 191 tests, 23 skipped.
