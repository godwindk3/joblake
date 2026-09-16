# Airflow validation — 2026-09-07

Historical validation, not a current health check.



- Docker image build thành công; Compose hợp lệ, API và scheduler healthy.
- DAG import/dependency check qua trên Airflow 3.3.1; `joblake_itviec` đã được
  đăng ký, để paused và chưa có lịch tự động.
- 86 unit test qua cả trên Windows và trong venv Linux của image.
- Smoke test dùng YAML tạm: một trang Hà Nội tìm được 20 URL, 12 URL mới.
- Tổng cộng sáu detail đầu hàng đợi trả HTTP 410, được ghi là đã mất vĩnh viễn.
  Parse chạy thành công nhưng `processed=0`; chưa xác nhận một bản ghi mới đi
  hết đường browser -> MinIO -> PostgreSQL trong lần thử này.
- Không sửa YAML ITviec gốc và không chạy Supabase sync.
