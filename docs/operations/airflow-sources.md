# Airflow cho các nguồn website

Mỗi website có một DAG riêng, cùng luồng `discovery -> detail -> parse`.

| DAG | Config đọc khi task bắt đầu | Giới hạn detail hiện tại |
| --- | --- | --- |
| `joblake_itviec` | `configs/itviec.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_vietnamworks` | `configs/vietnamworks.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_topdev` | `configs/topdev.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_topcv` | `configs/topcv.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_devwork` | `configs/devwork.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_careerviet` | `configs/careerviet.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_vieclam24h` | `configs/vieclam24h.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_careerlink` | `configs/careerlink.yaml` | 30/lượt |
| `joblake_jobsgo` | `configs/jobsgo.yaml` | `null`: toàn bộ URL đủ điều kiện |

JobsGO dùng requests, giữ query `slug` và phân trang bằng `page`.
DAG mặc định paused. Xem [hướng dẫn JobsGO](jobsgo.md).

CareerLink dùng CloakBrowser ở cả discovery/detail, trang đầu là URL gốc và phân trang qua `page`.
DAG mặc định paused. Xem [hướng dẫn CareerLink](careerlink.md).

Vieclam24h dùng requests, query `page` và giữ `sort_q`; DAG mặc định paused.
Xem [hướng dẫn Vieclam24h](vieclam24h.md).

CareerViet dùng requests với User-Agent `JobLake/0.1`, phạm vi ngành CNTT -
Phần mềm và DAG mặc định paused. Xem [hướng dẫn CareerViet](careerviet.md).

Devwork dùng HTTP requests cho cả discovery và detail, DAG mặc định paused.
Xem [phạm vi, phân trang và dữ liệu Devwork](devwork.md).

Giới hạn trên được đối chiếu với YAML ngày 2026-10-01; thay `detail.max_jobs_per_run`
trong config tương ứng nếu muốn thử ít hơn. Discovery và parse vẫn theo các
giới hạn riêng trong YAML. TopDev discovery dùng requests; các phase browser
dùng Xvfb và cấu hình browser hiện có. ITviec, TopCV và VietnamWorks cũng dùng
CloakBrowser cho cả hai phase. Tất cả nguồn dùng PostgreSQL state và MinIO;
parse hiện không giới hạn số job mỗi lượt. CareerLink có chờ khóa 60 giây,
dừng detail sau ba lỗi liên tiếp và không retry task detail ở Airflow.

## Chạy

### Chạy riêng một nguồn

1. Mở http://localhost:8080.
2. Chọn DAG cần chạy, unpause rồi Trigger.
3. Theo dõi từng task; task lỗi tự retry tối đa 2 lần, trừ detail CareerLink. Nếu vẫn lỗi, sửa nguyên
   nhân rồi Clear task lỗi, các phase sau cần chạy lại và `watcher`.

Cả chín DAG đều `schedule=None`, `catchup=False`, không có lịch tự động.
Các DAG mới được tạo ở trạng thái paused. Mỗi DAG có tối đa một active run
và một active task. Cả chín dùng pool `joblake_serial` ba slot (giữ tên pool
cũ để tương thích): tối đa ba task của ba website chạy song song bằng
LocalExecutor. Task chờ được chạy khi có slot trống; không chia cố định website
cho worker. Mỗi website vẫn chạy tuần tự discovery → detail → parse.
Raw cleanup chiếm cả ba slot để không chạy đồng thời với ingestion.

Khởi tạo Airflow tự đặt pool thành ba slot. Với runtime đã chạy, áp dụng bằng:

```powershell
docker compose -f orchestration/airflow/compose.yaml exec airflow-scheduler airflow pools set joblake_serial 3 'Up to three JobLake tasks across sources; cleanup reserves all slots'
```

Trên UI, trigger các DAG nguồn cần chạy; tối đa ba task chạy, phần còn lại chờ.
Giới hạn này áp dụng cho task Airflow, không giới hạn các lệnh CLI chạy riêng.

CLI gọi với `--strict`; kết quả `failed`/`blocked` hoặc exception làm task đỏ.
`suspicious` vẫn exit 0, không kích hoạt Airflow retry. Retry từng URL do
JobLake/PostgreSQL quản lý. Khóa theo
source ngăn CLI và Airflow chạy cùng nguồn đồng thời. Pause DAG không dừng task đang chạy.

## Retry và tiếp tục sau lỗi

- Mỗi phase có `retries=2` (tối đa 3 lượt chạy), `retry_delay=1 phút`,
  `retry_exponential_backoff=false`, `max_retry_delay=1 phút`. Riêng detail
  CareerLink có `retries=0`; fetcher và state vẫn áp dụng retry URL của nguồn.
  Không nhầm Airflow retry với backoff HTTP trong YAML.
- `detail` và `parse` dùng `all_done`: chờ phase trước kết thúc, bao gồm retry,
  rồi chạy kể cả phase trước failed/skipped. Detail xử lý URL đủ điều kiện
  trong PostgreSQL; parse xử lý HTML đã lưu. Không có dữ liệu đủ điều kiện
  thì có thể không làm thêm việc nào. Lỗi hạ tầng chung vẫn có thể làm cả ba phase lỗi.
- `watcher` phụ thuộc trực tiếp cả ba phase, dùng `one_failed`, không retry:
  có phase thất bại cuối cùng thì watcher fail; tất cả thành công thì watcher
  skipped. Nhờ vậy parse thành công không che lỗi của phase trước trong trạng thái DAG.
- Retry Airflow chạy lại toàn phase, tạo lượt pipeline mới và có thể xử lý
  thêm một batch. Nó không bỏ qua `next_retry_at` hay giới hạn attempts của URL.
- Run cũ đã có task `upstream_failed` không tự được sửa; cần Clear các task
  muốn chạy lại. Nếu chạy lại phase đầu, Clear cả phase sau và watcher để
  chúng phản ánh kết quả mới.

Code và YAML mount trực tiếp, không cần build lại image khi sửa/thêm DAG dùng dependency đã có.
Nếu scheduler đang dừng do một lượt crawl trước, kiểm tra và kết thúc run cũ
trên UI trước khi chủ động bật lại scheduler; việc thêm DAG không yêu cầu
khởi động lại lượt chạy cũ.

## Kiểm tra

```powershell
# Có thể dùng DAG processor để kiểm tra cả khi scheduler đang dừng.
docker compose -f orchestration/airflow/compose.yaml exec airflow-dag-processor python /opt/airflow/check_dag.py
```

Script kiểm tra cả chín DAG với Airflow thật: import, dependency, mapping đúng
source/phase/config, lịch thủ công, pool và giới hạn đồng thời. Lệnh này không
crawl website hoặc ghi dữ liệu nghiệp vụ. Tham khảo
[hướng dẫn runtime và storage](../setup/airflow.md) để setup từ đầu.

Supabase có CLI và DAG thủ công riêng `joblake_supabase_sync`, xử lý tất cả nguồn
và giữ ba slot. Sync tự verify snapshot đã stage trong cùng transaction trước
commit. Chưa tự nối ingestion với sync: chủ động chạy sau các phase cần thiết.
Một lần verify riêng về sau có thể thấy local đã thay đổi.

Health có DAG riêng `generate_report -> check_quality`, chạy lúc 07:00 khi được
unpause. Nó phát hiện chất lượng/freshness dù source task `suspicious` vẫn xanh.
Xem [health](data-health.md), [sync](supabase-cli.md) và [runbook](runbook.md).
Các source task chưa đặt `execution_timeout`; timeout request không phải giới
hạn tổng thời gian phase.
