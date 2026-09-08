# Chạy ITviec bằng Airflow local

> Đã bổ sung DAG VietnamWorks, TopDev và TopCV theo cùng runtime. Xem
> [hướng dẫn bốn source](airflow-sources.md). `check_dag.py` hiện kiểm tra cả bốn DAG.

Phạm vi: một DAG `joblake_itviec`, ba task `discovery -> detail -> parse`,
trigger thủ công (`schedule=None`), không catchup, không retry toàn task.
Scheduler dùng LocalExecutor. Pool `joblake_serial` có một slot và DAG chỉ có
một active run. Các DAG JobLake thêm sau cũng phải dùng pool này.

## Chuẩn bị và chạy

Yêu cầu Docker Desktop Linux containers, root `.env` đã cấu hình MinIO và
PostgreSQL, schema local đã migrate (`alembic upgrade head` bằng môi trường
Python của project). Airflow không tự migrate schema nghiệp vụ.
Các lệnh bên dưới chạy từ root repository:

```powershell
.\scripts\docker.ps1 start core
.\scripts\airflow.ps1 build
.\scripts\airflow.ps1 init
.\scripts\airflow.ps1 start

# Kiểm tra DAG bằng Airflow thật, không crawl hoặc ghi dữ liệu.
docker compose -f orchestration/airflow/compose.yaml exec airflow-scheduler python /opt/airflow/check_dag.py

# Kiểm tra browser đã được đóng gói.
docker compose -f orchestration/airflow/compose.yaml exec airflow-scheduler /opt/joblake/venv/bin/python -m cloakbrowser info
```

Mở http://localhost:8080, tìm `joblake_itviec`, unpause rồi Trigger DAG.
Task mặc định chỉ chạy khi bước trước thành công. Theo dõi log từng task.
Cấu hình ITviec hiện để `detail.max_jobs_per_run: null`; lượt đầu có thể dài.
Muốn thử ít, sửa giá trị này thành `5` trong `configs/itviec.yaml` trước khi
trigger; discovery vẫn xử lý các target/page được cấu hình. Không tự giới hạn
hay đổi target trong DAG.

## File nào được đọc khi nào?

- `configs/` và `src/` mount read-only từ host: YAML và code Python mới được
  đọc ở lần task khởi động tiếp theo, không cần restart Airflow.
- `data/state/` mount read-write: dùng đúng SQLite và browser state hiện có,
  giữ được dữ liệu khi tạo lại container. Không chạy CLI host đồng thời trên
  cùng state, vì pool chỉ điều phối task Airflow.
- Root `.env` mount read-only và CLI đọc lúc khởi động. Không copy secret
  vào image. Docker build context chỉ nhận các file code/dependency cần thiết.
- `MINIO_ENDPOINT` và `POSTGRES_HOST` trong container mặc định trỏ tới
  `host.docker.internal`, dùng các port đã publish của core stack trên Docker
  Desktop. `POSTGRES_PORT` và credential vẫn đọc từ root `.env`.
- Muốn đổi địa chỉ container, đặt `JOBLAKE_MINIO_ENDPOINT` hoặc
  `JOBLAKE_POSTGRES_HOST` trong `orchestration/airflow/.env`, rồi chạy `start`
  để Compose tạo lại container. Dùng `start`, không dùng `restart`, khi đổi
  cấu hình Compose/environment.
- Đổi dependency hoặc Dockerfile: chạy `build`, rồi `start`.
- Sửa YAML giữa hai lượt chạy để ba phase dùng cùng cấu hình.

JobLake có Python venv riêng trong image để dependency crawler không thay đổi
dependency Airflow. Browser binary được tải lúc build. `xvfb-run` cung cấp
màn hình ảo cho cấu hình `headless: false`; YAML vẫn quyết định chế độ browser.
Chạy browser trong Docker có thể cho kết quả khác host và cần kiểm tra trên
ITviec thật; màn hình ảo không đảm bảo website sẽ không chặn.

## Kết quả và chạy lại

Task gọi `python -m joblake.main --config configs/itviec.yaml --phase ... --strict`.
`completed` trả thành công (kể cả không còn job mới); `blocked`, `failed` và
`suspicious` trả exit code 1. Exception vẫn làm process thất bại.

Chế độ strict cố ý yêu cầu xem lại cả lỗi một phần: discovery thiếu target,
detail fetch/storage/validation lỗi, parse có rejected/failed/exhausted.
Record đã xử lý vẫn được giữ; CLI thường không có `--strict` giữ cách thoát
cũ. HTTP 410 được xử lý như URL đã mất vĩnh viễn, không làm fail batch.

Sau khi sửa nguyên nhân, dùng Clear task trong UI để chạy lại bước lỗi và
các bước downstream đang `upstream_failed`. Parse đọc HTML đã có trong MinIO,
không crawl lại website. Retry từng URL và thời điểm retry vẫn theo SQLite/YAML;
Clear task không bỏ qua `next_retry_at` hoặc giới hạn attempts. Một task thành
công không có nghĩa toàn bộ backlog đã hết (có thể còn URL đang chờ retry).
Record exhausted cần được xử lý theo state/parser policy, không chỉ Clear DAG.

Không có lịch tự động ở lần đầu. Sau khi chạy ổn, đặt schedule trong file DAG;
schedule, pool và Airflow retries không được điều khiển bởi YAML crawler.

## Supabase

Giữ bốn lệnh `supabase-test`, `supabase-sync --dry-run`, `supabase-sync`,
`supabase-verify` chạy tay như hiện tại. Sync mới xử lý tất cả source, không
lọc ITviec; do đó chưa gắn vào cuối DAG ITviec.

Sau khi bốn DAG source ổn định, thêm một DAG sync chung:
`supabase-test -> supabase-sync -> supabase-verify`. Dry run là bước kiểm tra
thủ công trước lần dùng đầu, không cần chạy trước mỗi sync. Không đưa
`supabase-migrate` vào lịch. Khi verify phải tránh parser chạy đồng thời;
pool một slot cho từng task chưa đủ đảm bảo không có parse chen giữa sync và
verify, nên cần phối hợp cả lượt chạy khi triển khai giai đoạn đó.

## Kiểm tra trước khi sử dụng

```powershell
python -m unittest discover -s tests
# Chỉ xác thực Compose, không in credential.
docker compose -f orchestration/airflow/compose.yaml config --quiet
```

`check_dag.py` kiểm tra import Airflow thật, dependency ba task, pool,
retry và strict flag. Cần chạy thêm một batch thực tế để xác nhận browser,
network và quyền ghi state của môi trường Docker trên máy.

### Kết quả kiểm tra ngày 2026-09-07

- Docker image build thành công; Compose hợp lệ, API và scheduler healthy.
- DAG import/dependency check qua trên Airflow 3.3.1; `joblake_itviec` đã được
  đăng ký, để paused và chưa có lịch tự động.
- 86 unit test qua cả trên Windows và trong venv Linux của image.
- Smoke test dùng YAML tạm: một trang Hà Nội tìm được 20 URL, 12 URL mới.
- Tổng cộng sáu detail đầu hàng đợi trả HTTP 410, được ghi là đã mất vĩnh viễn.
  Parse chạy thành công nhưng `processed=0`; chưa xác nhận một bản ghi mới đi
  hết đường browser -> MinIO -> PostgreSQL trong lần thử này.
- Không sửa YAML ITviec gốc và không chạy Supabase sync.
