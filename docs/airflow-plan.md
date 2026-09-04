# Kế hoạch đưa Apache Airflow vào JobLake

## 1. Phạm vi hiện tại

Giai đoạn này chỉ dựng **control plane Airflow độc lập** để đội dự án có
thể khởi động UI, scheduler, DAG processor và triggerer. Chưa có DAG gọi
`joblake`, chưa mount source code của project vào container Airflow, và
chưa tạo Airflow Connection tới MinIO hoặc PostgreSQL nghiệp vụ.

Điều này giữ nguyên hành vi hiện tại của các lệnh:

```powershell
python -m joblake.main --config configs/topdev.yaml
python -m joblake.main --config configs/topdev.yaml --phase parse
```

## 2. Quyết định kiến trúc cho môi trường local

| Thành phần | Lựa chọn | Lý do |
| --- | --- | --- |
| Airflow | `apache/airflow:3.3.1` | Pin phiên bản thay vì dùng tag `latest` |
| Executor | `LocalExecutor` | Phù hợp dev/single-node, chưa cần Redis và Celery worker |
| Metadata DB | PostgreSQL 16 riêng | Không trộn metadata Airflow với curated data của JobLake |
| Auth | Simple Auth Manager, all-admin | Chỉ dùng local; UI chỉ bind `127.0.0.1` |
| Deployment | Docker Compose riêng | Không làm `docker compose up` hiện tại tự khởi động Airflow |

Các service được dựng:

- `airflow-postgres`: metadata database của riêng Airflow.
- `airflow-init`: chạy migration trước khi các service dài hạn khởi động.
- `airflow-api-server`: UI và API tại `http://localhost:8080`.
- `airflow-scheduler`: lập lịch và chạy task qua `LocalExecutor`.
- `airflow-dag-processor`: parse DAG độc lập với scheduler.
- `airflow-triggerer`: phục vụ deferrable task về sau.

## 3. Cấu trúc thư mục

```text
orchestration/airflow/
├── compose.yaml
├── .env.example
├── config/
├── dags/
├── logs/            # sinh khi chạy, không commit
└── plugins/
```

`dags/` được để trống có chủ ý. Một file DAG mẫu cũng chưa được thêm vì
nó dễ tạo cảm giác project đã bắt đầu dùng Airflow để điều phối pipeline.

## 4. Khởi động local

Yêu cầu: Docker Desktop chạy Linux containers, Docker Compose 2.14 trở
lên, và cấp ít nhất 4 GB RAM cho Docker (khuyến nghị 8 GB).

Cách ngắn gọn nhất là dùng script cấp project tại `scripts/docker.ps1`.
Mặc định script điều khiển cả MinIO, PostgreSQL JobLake và Airflow:

```powershell
# Xem toàn bộ action được hỗ trợ.
.\scripts\docker.ps1 help

# Lần chạy đầu tiên.
.\scripts\docker.ps1 config
.\scripts\docker.ps1 pull
.\scripts\docker.ps1 init
.\scripts\docker.ps1 start

# Các lần sử dụng sau.
.\scripts\docker.ps1 status
.\scripts\docker.ps1 logs
.\scripts\docker.ps1 stop
.\scripts\docker.ps1 start

# Chỉ thao tác một phần khi cần debug.
.\scripts\docker.ps1 restart core
.\scripts\docker.ps1 logs airflow
```

Script tự dùng `.env` tương ứng của từng stack. Action `reset` xóa data
volume local của scope được chọn nên yêu cầu xác nhận rõ ràng. File
`scripts/airflow.ps1` vẫn được giữ làm shortcut chỉ dành cho Airflow.

Các lệnh Docker Compose tương đương được giữ bên dưới để hỗ trợ debug.

Các lệnh sau chạy từ root của repository:

```powershell
# Tùy chọn: tạo file override và thay các secret dev mặc định.
Copy-Item orchestration/airflow/.env.example orchestration/airflow/.env

# Validate cấu hình trước khi tải image hoặc tạo container.
docker compose --env-file orchestration/airflow/.env `
  -f orchestration/airflow/compose.yaml config

# Migration metadata DB lần đầu hoặc sau khi nâng Airflow.
docker compose --env-file orchestration/airflow/.env `
  -f orchestration/airflow/compose.yaml up airflow-init

# Khởi động control plane.
docker compose --env-file orchestration/airflow/.env `
  -f orchestration/airflow/compose.yaml up -d
```

Nếu không tạo `.env`, bỏ phần `--env-file ...`; Compose dùng các giá trị
dev mặc định có sẵn trong `compose.yaml`.

Mở `http://localhost:8080`. Local setup hiện không hỏi mật khẩu vì
`SIMPLE_AUTH_MANAGER_ALL_ADMINS=true` và cổng chỉ bind vào localhost.

Kiểm tra và xem log:

```powershell
docker compose -f orchestration/airflow/compose.yaml ps
docker compose -f orchestration/airflow/compose.yaml logs -f --tail 200
```

Dừng service nhưng giữ metadata:

```powershell
docker compose -f orchestration/airflow/compose.yaml down
```

Chỉ dùng lệnh dưới khi muốn reset toàn bộ metadata Airflow local:

```powershell
docker compose -f orchestration/airflow/compose.yaml down --volumes
```

## 5. Ranh giới tích hợp

Hiện tại hai vùng hoàn toàn độc lập:

```text
Airflow control plane              JobLake data plane
---------------------              ------------------
Airflow metadata PostgreSQL        crawler/parser CLI
Scheduler/API/DAG processor        SQLite crawl state
Empty dags/                        MinIO raw objects
                                   curated PostgreSQL
```

Không dùng PostgreSQL `joblake-postgres` làm Airflow metadata DB. Hai loại
dữ liệu có vòng đời, migration, backup và quyền truy cập khác nhau.

## 6. Roadmap tích hợp sau giai đoạn setup

### Giai đoạn 1 — Làm pipeline sẵn sàng để được điều phối

- Chuẩn hóa logging thay cho `print`, đưa `run_id`, `source`, `phase` vào log.
- Bảo đảm từng phase idempotent, có exit code rõ ràng và retry an toàn.
- Validate YAML config ngay khi khởi động.
- Xử lý các lỗi P0 trong `docs/architecture-review.md`, đặc biệt blocked
  attempt và kiểm tra hash MinIO, trước khi scheduler tự động chạy lặp.
- Quyết định chuyển crawl state từ SQLite sang PostgreSQL trước khi chạy
  task trên nhiều container/host.

### Giai đoạn 2 — Đóng gói runtime JobLake cho Airflow

- Tạo custom Airflow image pin cả Airflow lẫn dependency JobLake.
- Không `pip install` dependency lúc container startup.
- Mount/copy `configs/` theo chế độ read-only.
- Tạo network chung có tên rõ ràng cho Airflow và data services.
- Khai báo MinIO/PostgreSQL bằng Airflow Connections hoặc secrets backend;
  không hard-code credential trong DAG.

### Giai đoạn 3 — Thiết kế DAG

- Tách task theo phase: `discovery -> detail -> parse`; không nhét toàn bộ
  pipeline vào một Python callable dài.
- Một DAG hoặc DAG factory theo source, với schedule và giới hạn concurrency
  riêng cho từng website.
- Dùng Airflow Pool theo domain để bảo vệ rate limit/politeness.
- Retry chỉ cho lỗi tạm thời; lỗi dữ liệu hoặc 404 phải kết thúc rõ ràng.
- Truyền identifier nhỏ qua XCom; HTML/raw payload tiếp tục nằm ở MinIO.
- Bổ sung smoke test để DAG import không lỗi trước khi deploy.

### Giai đoạn 4 — Vận hành production

- Thay local all-admin auth bằng auth manager phù hợp và TLS/reverse proxy.
- Chuyển secrets sang secret backend, sinh Fernet/JWT/API keys thật.
- Bật remote task logging và metrics/alerting.
- Khi throughput buộc phải scale ngang, đánh giá CeleryExecutor hoặc
  KubernetesExecutor; không thêm Redis/Celery trước khi có nhu cầu đo được.
- Thiết kế backup và upgrade riêng cho Airflow metadata database.

## 7. Tiêu chí hoàn tất setup hiện tại

- `docker compose ... config` hợp lệ.
- `airflow-init` exit code 0.
- API server, scheduler, DAG processor và triggerer cùng chạy.
- UI mở được tại localhost và danh sách DAG không chứa example DAG.
- Các test/CLI hiện tại của JobLake không đổi hành vi.
- Không có Airflow Connection, Variable hoặc DAG tương tác với JobLake.
