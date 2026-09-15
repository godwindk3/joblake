# Airflow cho bốn website

Mỗi website có một DAG riêng, cùng luồng `discovery -> detail -> parse`.

| DAG | Config đọc khi task bắt đầu | Giới hạn detail hiện tại |
| --- | --- | --- |
| `joblake_itviec` | `configs/itviec.yaml` | `null`: toàn bộ URL đủ điều kiện |
| `joblake_vietnamworks` | `configs/vietnamworks.yaml` | 20/lượt |
| `joblake_topdev` | `configs/topdev.yaml` | 20/lượt |
| `joblake_topcv` | `configs/topcv.yaml` | `null`: toàn bộ URL đủ điều kiện |

Giới hạn trên là giá trị YAML lúc tích hợp; thay `detail.max_jobs_per_run`
trong config tương ứng nếu muốn thử ít hơn. Discovery và parse vẫn theo các
giới hạn riêng trong YAML. TopDev discovery dùng requests; các phase browser
dùng Xvfb và cấu hình browser hiện có.

## Chạy

### Chạy riêng một nguồn

1. Mở http://localhost:8080.
2. Chọn DAG cần chạy, unpause rồi Trigger.
3. Theo dõi từng task; task lỗi tự retry tối đa 2 lần. Nếu vẫn lỗi, sửa nguyên
   nhân rồi Clear task lỗi, các phase sau cần chạy lại và `watcher`.

Cả bốn DAG đều `schedule=None`, `catchup=False`, không có lịch tự động.
Ba DAG mới được tạo ở trạng thái paused. Mỗi DAG có tối đa một active run
và một active task. Cả bốn dùng pool `joblake_serial` một slot: dù trigger
nhiều website, chỉ một task JobLake chạy tại một thời điểm. Các task thuộc
những website khác nhau có thể xen kẽ giữa các phase.

CLI gọi với `--strict`; kết quả `failed`/`blocked` hoặc exception làm task đỏ.
`suspicious` vẫn exit 0, không kích hoạt Airflow retry. Retry từng URL do
JobLake/PostgreSQL quản lý. Khóa theo
source ngăn CLI và Airflow chạy cùng nguồn đồng thời. Pause DAG không dừng task đang chạy.

## Retry và tiếp tục sau lỗi

- Mỗi phase có `retries=2` (tối đa 3 lượt chạy), `retry_delay=5 phút`,
  exponential backoff và trần 30 phút. Airflow có jitter nên thời gian chờ
  thực tế có thể khác 5/10 phút.
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

Code và YAML mount trực tiếp, không cần build lại image khi thêm ba DAG này.
Nếu scheduler đang dừng do một lượt crawl trước, kiểm tra và kết thúc run cũ
trên UI trước khi chủ động bật lại scheduler; việc thêm DAG không yêu cầu
khởi động lại lượt chạy cũ.

## Kiểm tra

```powershell
# Có thể dùng DAG processor để kiểm tra cả khi scheduler đang dừng.
docker compose -f orchestration/airflow/compose.yaml exec airflow-dag-processor python /opt/airflow/check_dag.py
```

Script kiểm tra cả bốn DAG với Airflow thật: import, dependency, mapping đúng
source/phase/config, lịch thủ công, pool và giới hạn đồng thời. Lệnh này không
crawl website hoặc ghi dữ liệu nghiệp vụ. Tham khảo
[hướng dẫn runtime và storage](../setup/airflow.md) để setup từ đầu.

Supabase vẫn chạy bằng CLI riêng và sync tất cả source. Chưa tự nối sync vào
bốn DAG: cần phối hợp thời điểm sync/verify với các lượt parse trước khi tự
động hóa; một pool theo task không đảm bảo parse không chen giữa sync và verify.
