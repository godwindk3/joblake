# Storage audit — 2026-09-07

Historical inventory; sizes and runtime settings may have changed.



Diagnostics hiện có 54 HTML (~39.55 MiB), 54 PNG (~8.53 MiB), 55 JSON
(~4.72 MiB): tổng ~52.8 MiB. Airflow logs có 83 file (~3.29 MiB).
SQLite ~7.11 MiB. Đây là số đo file trên host, không bao gồm Docker volumes,
MinIO hay PostgreSQL đang chạy. Chưa xóa dữ liệu thật trong lần triển khai.

| Điểm | Cơ chế tăng | Hướng xử lý tiếp theo |
| --- | --- | --- |
| Diagnostics | Mỗi capture thêm HTML/PNG/JSON; trước đây success cũng được lưu | Đã có bật/tắt, error-only, TTL và giới hạn số bộ |
| Airflow task logs | Bind mount `orchestration/airflow/logs`; chưa có cleanup trong repo | Thêm cleanup log đã kết thúc theo TTL, không xóa task đang chạy |
| Docker service logs | Hai Compose chưa khai báo rotation; daemon có thể có cấu hình riêng | Kiểm tra daemon rồi đặt `max-size`/`max-file`; chưa đo volume thực tế |
| SQLite state | `crawl_runs`, `discovery_targets`, `fetch_attempts`, `parse_attempts` tích lũy lịch sử | Archive theo tuổi, bảo toàn FK và state retry; không xóa DB queue |
| PostgreSQL parse history | Giữ kết quả theo raw hash/parser version | Lịch sử có giá trị; chỉ archive sau khi xác định nhu cầu audit/reparse |
| MinIO discovery HTML | Nếu `store_discovery` bật, mỗi trang/lượt có key timestamp mới | Cả 4 YAML đang false; giữ false hoặc thêm lifecycle riêng prefix discovery |
| MinIO detail | Key cố định theo URL; số URL tăng thì object tăng; nếu bucket có versioning, overwrite có thể giữ bản cũ | Kiểm tra versioning/lifecycle trên bucket; không xóa raw đang được DB tham chiếu |
| RAM discovery | `run_records` giữ mọi URL/record duy nhất trong một run | Giới hạn số trang/batch; với crawl lớn chuyển dedup sang state và giữ counter |
| RAM HTML | Fetch, encode và parse đọc toàn bộ HTML; MinIO `read_object` dùng `response.read()` | Nếu gặp trang lớn, thêm giới hạn kích thước payload ở fetch/read trước khi parse |
| Local raw temp | Atomic write có finally xóa `.tmp`, nhưng kill process/mất điện có thể bỏ sót | Cleanup file tạm cũ khi không còn writer; đây chỉ áp dụng local raw backend |

Không phải mọi `fetchall()` đều tải toàn bảng: sample Supabase đã `LIMIT 5`,
sync đọc theo batch 200. Browser storage state ghi đè một path cố định, không
tạo file mới mỗi request. Vì vậy ưu tiên tiếp theo là retention log và theo
dõi kích thước state/raw, thay vì xóa các dữ liệu nghiệp vụ còn tham chiếu.
