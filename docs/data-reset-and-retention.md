# Reset dữ liệu và cơ chế hết hạn hiện tại

## Reset đã thực hiện ngày 2026-09-08

Đã kiểm kê khi Airflow/crawler dừng, rồi xóa dữ liệu cũ theo yêu cầu:

- MinIO `joblake/raw/detail/`: 1.398 object, 922.098.030 byte.
- PostgreSQL local: 1.398 parse results, 1.398 postings, 4 sources.
- Supabase: 627 parse results, 627 postings, 4 sources.
- SQLite: 5.798 jobs, 53 runs, 2.887 fetch attempts, 1.398 raw objects,
  2.019 parse attempts; xóa file DB để lượt mới khởi tạo lại.
- Browser state, diagnostics, local raw và file log Airflow cũ.
- Metadata Airflow trong volume `joblake-airflow_airflow_postgres_data`.

Ba bảng `core.job_parse_results`, `core.source_job_postings`, `ref.sources`
được TRUNCATE RESTART IDENTITY, không CASCADE. Giữ schema/index/grants,
bucket MinIO, credentials/config và lifecycle. Không tạo backup mới.
Đã xác minh cả local, Supabase và bucket đều trống trước khi chạy mới.

Bốn DAG được yêu cầu chạy đúng một lần với run ID `fresh_reset_20260908`.
Giữ YAML hiện tại: detail VietnamWorks/TopDev tối đa 20 job/lượt,
ITviec/TopCV không đặt giới hạn batch. Vì vậy một lượt không đồng nghĩa
mọi URL discovery được crawl hết. DAG chỉ ghi PostgreSQL local; Supabase
đã được làm trống và không tự nhận lại dữ liệu nếu chưa chạy sync.

## Các loại hết hạn không đồng nghĩa với nhau

| Loại | Cơ chế hiện tại | Có tự xóa dữ liệu? |
| --- | --- | --- |
| Raw HTML MinIO | Rule bật, prefix `raw/detail/`, Expiration Days=45; versioning chưa bật | Có, MinIO thực thi lifecycle; không xóa DB theo |
| Diagnostics | 7 ngày, tối đa 100 bộ/directory; cleanup khi diagnostics khởi tạo/lưu | Có; tắt diagnostics thì không chạy cleanup |
| Tin tuyển dụng `expires_at` | Một số parser lấy `validThrough`, lưu PostgreSQL | Không có job/trigger tự xóa hay tự ẩn tin |
| `is_current` | Chỉ chọn phiên bản parse hiện hành của posting | Không phản ánh tin còn tuyển hay chưa hết hạn |
| `last_seen_at` | Cập nhật khi discovery gặp lại URL | Không có TTL hoặc auto-expire khi URL lâu không xuất hiện |
| Retry detail | Chờ 3.600 giây, tối đa 3 attempts theo YAML | Không; chỉ điều khiển lần thử tiếp theo |
| Claim parse treo | Sau 3.600 giây đủ điều kiện phục hồi khi parse chạy lại | Không; đây là thời hạn claim, không phải TTL bản ghi |
| SQLite history | Không có retention/archive/VACUUM định kỳ trong repo | Không |
| PostgreSQL/Supabase | Không có retention job trong repo; sync không DELETE remote-only rows | Không |
| Airflow task logs/metadata | Chưa cấu hình cleanup định kỳ trong repo | Không |
| Docker log | Lần kiểm tra trước: json-file không có max-size/max-file ở core/scheduler | Không thấy giới hạn rotation được cấu hình |
| Browser cookies/session | Server/cookie có expiry riêng; file storage state được ghi đè | Không có TTL xóa file local |

Không kiểm kê lịch tùy chỉnh ngoài project trên Supabase (ví dụ job do người
dùng cấu hình riêng). Các kết luận DB ở trên là cơ chế do JobLake triển khai;
audit các bảng hiện tại không thấy user trigger ở core/ref.

## Khoảng trống giữa lifecycle MinIO và state

`_audit_raw_objects()` chạy lúc ingestion discovery/detail khởi động nếu
`integrity_check_on_start` bật, kiểm tra tối đa 100 object/source/lượt theo YAML.
Object mất được gắn `raw_objects.integrity_status=missing`,
`jobs.raw_status=storage_missing`. Queue detail chỉ claim pending,
retryable_error, blocked nên storage_missing không tự crawl lại.

Parse cần raw đã lưu; object hết hạn khiến không thể reparse với phiên bản
parser mới. Kết quả đã parse trong PostgreSQL/Supabase vẫn tồn tại và có thể
vẫn is_current=true. Đây không phải cơ chế “tin hết hạn sau 45 ngày”.

Nên tách rõ chính sách lưu bằng chứng raw 45 ngày với thời hạn phục vụ tin:
thêm trạng thái raw_expired hoặc chính sách xử lý storage_missing, cùng
quy tắc lọc tin theo expires_at/last_seen_at khi cần. Chưa thay đổi các quy
tắc này trong lần reset.

## Công cụ bảo trì

`scripts/audit_retention.py` chỉ đọc lifecycle, versioning, số bản ghi và
object; không in credential. `scripts/reset_joblake_data.py` là bước phá hủy
dữ liệu service local + Supabase đã dùng trong lần reset này. Nó KHÔNG phải
lệnh reset hoàn chỉnh: phải dừng writer, audit phạm vi, dọn SQLite/host state
và metadata Airflow tương ứng, xác minh rỗng rồi mới khởi chạy lại. Không có
transaction chung giữa local, Supabase và MinIO; nếu bước nào lỗi phải kiểm
tra lại từng store. Không dùng lại để reset khi một lượt crawl đang chạy.
