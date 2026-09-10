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
3. Theo dõi từng task; khi lỗi, sửa nguyên nhân rồi Clear task lỗi và các
   task downstream bị `upstream_failed`.

Cả bốn DAG đều `schedule=None`, `catchup=False`, không có lịch tự động.
Ba DAG mới được tạo ở trạng thái paused. Mỗi DAG có tối đa một active run
và một active task. Cả bốn dùng pool `joblake_serial` một slot: dù trigger
nhiều website, chỉ một task JobLake chạy tại một thời điểm. Các task thuộc
những website khác nhau có thể xen kẽ giữa các phase.

CLI gọi với `--strict`; lỗi hoặc kết quả `suspicious` làm task đỏ. Không có
Airflow retry tự động; retry từng URL do JobLake/SQLite quản lý. Không chạy
CLI Windows đồng thời trên cùng SQLite. Pause DAG không dừng task đang chạy.

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
[hướng dẫn runtime và storage](airflow-itviec.md) để setup từ đầu.

Supabase vẫn chạy bằng CLI riêng và sync tất cả source. Chưa tự nối sync vào
bốn DAG: cần phối hợp thời điểm sync/verify với các lượt parse trước khi tự
động hóa; một pool theo task không đảm bảo parse không chen giữa sync và verify.
