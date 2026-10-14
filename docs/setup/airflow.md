# Airflow local setup

Runtime dùng chung cho 15 DAG: DAG tổng `joblake_daily`, chín nguồn, sync, enrichment, enrichment backfill, data health và raw cleanup. Xem [vận hành các source](../operations/airflow-sources.md) để biết retry, pool, giới hạn và cách trigger.

## Hằng ngày: bật một lần, chạy cả pipeline

Sau khi đã hoàn tất setup và tạo container một lần, **chỉ cần mở Docker Desktop**
để Docker Engine khởi động. Bảy service chạy lâu dài (MinIO, PostgreSQL local,
PostgreSQL metadata và bốn service Airflow) dùng `restart: always`, nên tự bật
lại kể cả đã Stop container trước đó. `airflow-init` giữ `restart: "no"` vì chỉ
dùng cho khởi tạo/migration. Không cần lệnh PowerShell hằng ngày.

Lệnh dưới chỉ dùng cho setup lần đầu, áp dụng thay đổi Compose, hoặc tạo lại
container đã bị xóa:

```powershell
.\scripts\docker.ps1 start
```

Lệnh này bật cả PostgreSQL/MinIO và Airflow. Mở http://localhost:8080 và theo dõi **`joblake_daily`**;
không cần Trigger từng DAG hoặc unpause các DAG nguồn. DAG tổng mới được tạo ở
trạng thái unpaused và chạy thật ngay khi scheduler nhận lịch đến hạn.

Mở lại cửa sổ Docker Desktop khi Engine vẫn đang chạy không phải là khởi động
lại Engine: nếu đã Stop container trong phiên đó, bấm Start nhóm container
hoặc Quit Docker Desktop rồi mở lại. Đóng cửa sổ Docker Desktop có thể chỉ ẩn
ứng dụng; dùng Quit để tắt Engine. Không xóa container/volume nếu muốn giữ lịch
và trạng thái. Muốn ngừng tự cào lâu dài, pause `joblake_daily` trong Airflow;
Stop container chỉ dừng đến lần Engine khởi động tiếp theo.

Luồng: **9 nhóm nguồn (discovery → detail → parse) → enrichment → kiểm tra kết nối
→ sync Supabase → raw cleanup**. Các bước chạy trực tiếp trong DAG tổng, không tạo
12 lượt chạy ở các DAG riêng. Tối đa ba task dùng pool `joblake_serial` cùng lúc;
sync và cleanup giữ cả ba slot. Một lượt tổng đang chạy sẽ chặn lượt tổng tiếp theo.

- Lịch theo ngày, mốc 00:00 Asia/Ho_Chi_Minh, dùng `CronDataIntervalTimetable`
  với `catchup=False`: bật muộn vẫn chạy lượt đến hạn gần nhất, bỏ qua ngày cũ.
  Bật lại cùng ngày không tạo thêm lượt theo lịch; nếu giữ máy bật qua đêm,
  lượt tiếp theo đến hạn lúc 00:00. Run cũ chưa xong vẫn cần hoàn tất/khắc phục.
- Logical date trên UI là đầu khoảng dữ liệu (ngày trước), không phải giờ bật máy.
  Lịch này không lọc crawler theo ngày; crawler vẫn đọc YAML/state hiện có.
- `dry_run=false`: enrichment gọi API và sync ghi Supabase. `max_jobs=100` là
  giới hạn API attempts/lượt; quota, thời gian và queue retry trong YAML vẫn áp dụng.
  Một lượt thành công không đảm bảo đã xử lý hết backlog enrichment.
- `apply=true`: cleanup xóa raw theo policy hiện có (expired ≥7 ngày hoặc unknown
  ≥30 ngày cùng các điều kiện bảo vệ), tối đa 200 object/250 MiB mỗi attempt.
  Retry có budget mới. Không xóa dữ liệu parsed trong PostgreSQL.
- Một nguồn lỗi không chặn nguồn khác. Sau khi mọi phase cào kết thúc, enrichment,
  sync và cleanup vẫn được thử; sync chỉ chạy nếu kiểm tra kết nối thành công.
  Enrichment lỗi vẫn cho phép sync dữ liệu hiện có. `watcher` giữ trạng thái lượt
  tổng là failed nếu bất kỳ bước nào lỗi, kể cả khi cleanup cuối cùng thành công.
- Muốn dừng lịch: pause **`joblake_daily`**; pause không hủy task đang chạy.
  Muốn thử riêng: dùng các DAG thủ công. Không trigger cùng nguồn trong lúc lượt
  tổng đang chạy. Raw cleanup riêng đã bỏ lịch 15:00 để tránh chạy hai lần.
- Chỉnh mặc định lịch chạy trong `orchestration/airflow/dags/joblake_daily.py`;
  tham số nhập khi Trigger chỉ áp dụng cho lượt thủ công đó. `dry_run=true` chỉ
  preview enrichment/sync; muốn preview cleanup phải đặt thêm `apply=false`.
  Crawler vẫn chạy thật. Sửa lỗi rồi Clear task cần chạy lại cùng downstream và
  `watcher`, thay vì Trigger lại cả chín nguồn.

DAG/config được mount trực tiếp nên thay đổi này không cần build lại image.
Nếu đã chủ động pause DAG tổng, khởi động lại không tự unpause; bật lại trên UI.

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
Detail và parse dùng `all_done`, nên vẫn chạy sau khi phase trước kết thúc với lỗi. Theo dõi log từng task.
Cấu hình ITviec hiện để `detail.max_jobs_per_run: null`; lượt đầu có thể dài.
Muốn thử ít, sửa giá trị này thành `5` trong `configs/itviec.yaml` trước khi
trigger; discovery vẫn xử lý các target/page được cấu hình. Không tự giới hạn
hay đổi target trong DAG.

## File nào được đọc khi nào?

- `configs/` và `src/` mount read-only từ host: YAML và code Python mới được
  đọc ở lần task khởi động tiếp theo, không cần restart Airflow.
- `data/state/` mount read-write: giữ browser state, diagnostics, health report
  và các snapshot SQLite cũ nếu có. Queue hiện tại nằm trong PostgreSQL.
  Pool chỉ điều phối Airflow; khóa PostgreSQL theo source phối hợp thêm với CLI.
  Không cố chạy nhiều phase cùng nguồn ngoài cơ chế khóa.
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
`completed` và `suspicious` trả thành công; `blocked` và `failed` trả exit code 1. Exception vẫn làm process thất bại.

Record đã xử lý vẫn được giữ. HTTP 410 được xử lý như URL đã mất vĩnh viễn.
`watcher` làm DAG fail khi một phase fail cuối cùng; `suspicious` cần được theo
dõi qua health report và bước `check_quality`.

Sau khi sửa nguyên nhân, dùng Clear task trong UI để chạy lại bước lỗi và
các bước downstream cần chạy lại cùng `watcher`. Parse đọc HTML đã có trong MinIO,
không crawl lại website. Retry từng URL và thời điểm retry theo PostgreSQL/YAML;
Clear task không bỏ qua `next_retry_at` hoặc giới hạn attempts. Một task thành
công không có nghĩa toàn bộ backlog đã hết (có thể còn URL đang chờ retry).
Record exhausted cần được xử lý theo state/parser policy, không chỉ Clear DAG.

Các DAG riêng của chín nguồn, sync, enrichment, enrichment backfill và raw cleanup
không có lịch tự động; `joblake_daily` điều phối lịch hằng ngày. Data health có lịch
07:00 Asia/Ho_Chi_Minh, mặc định paused; unpause mới kích hoạt lịch. Schedule, pool
và Airflow retries nằm trong DAG, không nằm trong YAML crawler. Raw cleanup riêng
vẫn mặc định dry-run; cleanup trong DAG tổng mặc định `apply=true`.

## Supabase

DAG `joblake_supabase_sync` chạy thủ công (`schedule=None`), mặc định paused.
Unpause và bấm Trigger để đồng bộ trạng thái local hiện tại, không crawl lại.
Giữ `dry_run=false` để ghi dữ liệu; chọn `true` để chỉ xem số hàng sẽ thêm/sửa/xóa.
Luồng: `check_connection -> sync_active_jobs`; sync đối chiếu toàn bộ dữ liệu
với snapshot ngay trong transaction trước commit. Không cần task verify riêng
có thể đọc một snapshot local mới sau khi crawler chạy tiếp.

Task sync giữ cả ba slot của pool `joblake_serial`; `max_active_runs=1`.
Chỉ job active được xuất bản, expired/unknown bị loại; mỗi tin giữ một bản.
Xem [hướng dẫn Supabase](../operations/supabase-cli.md) để biết trường được lưu,
chính sách parse lỗi và cách kiểm tra. Không chạy legacy `supabase-migrate`.

## Enrichment và health

- `joblake_enrichment`: chạy thủ công, mặc định `dry_run=true`; queue riêng quản
  lý retry/quota, không tự chạy sau parse. Xem [enrichment](../operations/enrichment.md).
- `joblake_enrichment_backfill`: chạy bù job cũ còn active, mặc định dry run,
  30 ngày gần nhất theo `first_seen_at`, mới nhất trước, tối đa 100 job/lượt.
  Có bộ lọc ngày/nguồn/ID; xem [hướng dẫn backfill](../operations/enrichment-backfill.md).
- `joblake_data_health`: `generate_report -> check_quality`. Report JSON/Markdown
  được lưu trước; check quality không retry, trả lỗi khi vượt ngưỡng. Generation
  vẫn retry lỗi DB/file hai lần. `configs/data_health.yaml` cho phép override theo
  nguồn; gate yêu cầu snapshot mới trong một giờ. Xem [health](../operations/data-health.md).
- Không có dịch vụ gửi email/chat hoặc tự khắc phục dữ liệu được cấu hình.

## Kiểm tra trước khi sử dụng

```powershell
python -m unittest discover -s tests
# Chỉ xác thực Compose, không in credential.
docker compose -f orchestration/airflow/compose.yaml config --quiet
```

`check_dag.py` kiểm tra import Airflow thật, dependency ba phase và watcher, pool,
retry, strict flag, sync/enrichment và dependency health gate. CI cũng build image
và chạy script này. Cần chạy thêm một batch thực tế để xác nhận browser,
network và quyền ghi state của môi trường Docker trên máy.
