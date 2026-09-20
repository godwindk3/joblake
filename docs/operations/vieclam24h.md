# Vieclam24h

Source `vieclam24h` discovery tại
`https://vieclam24h.vn/viec-lam-it-phan-mem-o8.html`, tăng query `page`
từ 1 và giữ `sort_q=priority_max,desc`. Không crawl riêng URL không có
query vì đó cũng là trang đầu.

## Discovery và detail

Hai phase dùng requests với User-Agent `JobLake/0.1`, không cần đăng nhập.
Đọc `getJobList.data.total_pages` từ JSON `__NEXT_DATA__` để xác định trang
cuối; giới hạn tự động 200 trang. Nếu thiếu metadata, discovery báo lỗi
phát hiện phân trang. URL chỉ được nhận nếu ID có trong `getJobList.items`;
query theo dõi `open_from`, `search_id` và fragment được loại bỏ.

Không giới hạn detail vào slug `it-phan-mem`: danh sách này có cả công việc
ngành IT phần cứng, Giáo dục, Marketing và các ngành khác. Lưu đúng ngành
của từng job, không tự gán mọi tin thành IT.

Detail phải có HTTP hợp lệ, host đúng, ID từ URL khớp với dữ liệu detail
và canonical, tiêu đề và nội dung thực sự được render. JSON-LD `identifier`
của nguồn này là **mã công ty**, không dùng làm mã job. Slug khác nhau nhưng
cùng job ID trong request/canonical vẫn được chấp nhận.

Parser đọc mô tả, yêu cầu và quyền lợi từ các trường riêng trong JSON,
không tách từ chuỗi description gộp của JSON-LD. Ngành nghề, địa điểm,
kinh nghiệm, hình thức làm việc được ánh xạ bằng danh mục `initCommon`
có ngay trong HTML. Ngày đăng và hạn nộp dùng JSON-LD. Không lưu toàn bộ
hydration payload vào parsed data; chỉ giữ metadata cần thiết.

`domains_raw` để trống vì chưa có lĩnh vực doanh nghiệp rõ ràng;
`skills_raw` lấy từ `skills_new` khi có. Vì vậy tin có thể đạt `partial`,
là chất lượng được hệ thống chấp nhận.

## Chạy

Config dùng MinIO/PostgreSQL hiện tại, không cần migration riêng:

```powershell
python -m joblake.main --config configs/vieclam24h.yaml --phase discovery --strict
python -m joblake.main --config configs/vieclam24h.yaml --phase detail --strict
python -m joblake.main --config configs/vieclam24h.yaml --phase parse --strict
```

DAG `joblake_vieclam24h` mặc định paused, chạy thủ công, chung pool
`joblake_serial`. Detail xử lý toàn bộ URL đủ điều kiện theo mặc định
(`max_jobs_per_run: null`).

## Kiểm tra 2026-09-19

- HTTP fetcher thật đã duyệt 14 trang. Số URL lấy ra khớp số ID job trong
  metadata trên từng trang.
- Ba detail người dùng cung cấp và năm tin từ các trang 1/4/7/10/14:
  cả tám validate thành công và parse ở mức `partial`.
- Fixtures được rút gọn từ HTML thật, bỏ các trường liên hệ/tài khoản không
  phục vụ parser. Test gồm tracking URL, ngành khác slug, mã job/công ty,
  phân trang, metadata thiếu, redirect sang job khác và HTML chưa đủ nội dung.
- Smoke test không ghi database/MinIO, không kích hoạt DAG. DAG chỉ được
  kiểm tra cú pháp, chưa xác minh import trong Airflow thật.

```powershell
python -m unittest discover -s tests -p test_vieclam24h.py
```
