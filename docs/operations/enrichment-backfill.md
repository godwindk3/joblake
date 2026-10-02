# Enrichment backfill

DAG `joblake_enrichment_backfill` xử lý bù job cũ, gồm dữ liệu bị cutoff 26/09
loại khỏi DAG enrichment thông thường. Chỉ chọn bản parse hiện tại đạt
`accepted/partial` của job còn `active`. Không crawl hoặc parse lại HTML.

## Chạy từ Airflow

1. Tìm `joblake_enrichment_backfill`, unpause nếu cần và chọn **Trigger DAG**.
2. Giữ `dry_run=true`, chỉnh bộ lọc, chạy task `backfill_jobs` rồi mở **Logs**.
3. Xem dòng `Backfill counts` và `Backfill dry-run report`: số khớp bộ lọc,
   đã thành công, failed/hết retry, đang xử lý, chờ retry, sẵn sàng và được chọn.
4. Khi muốn chạy thật, trigger lần mới với `dry_run=false`. Copy `as_of`,
   `date_from`, `date_to` từ report để giữ nguyên cửa sổ thời gian đã xem.
5. Chạy `joblake_supabase_sync` riêng để đưa kết quả thành công lên serving.

DAG chạy thủ công, không tự chạy lại ngày hôm sau. Giới hạn thời gian dùng chung
config enrichment (mặc định 20 phút, timeout task 25 phút). Không tự retry task;
queue giữ lịch sử retry. Hết quota thì giữ công việc trong queue để lần sau chạy tiếp.

## Tham số

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `dry_run` | `true` | Transaction read-only; không enqueue, recover, gọi model hoặc ghi DB |
| `lookback_days` | `30` | Số ngày tính lùi từ `date_to` hoặc thời điểm bắt đầu task |
| `date_from` | `null` | Mốc đầu, bao gồm; nhập giá trị này để thay `lookback_days` |
| `date_to` | `null` | Mốc cuối, không bao gồm; mặc định `as_of` |
| `as_of` | `null` | Mốc tham chiếu cố định; mặc định thời điểm CLI bắt đầu chạy |
| `date_field` | `first_seen_at` | Ngày phát hiện; hoặc `posted_at` (ngày đăng), `fetched_at` (ngày fetch) |
| `sources` | `[]` | Mã nguồn, ví dụ `["topcv", "itviec"]`; rỗng lấy tất cả |
| `posting_ids` | `[]` | ID của `core.source_job_postings`; rỗng lấy tất cả |
| `sort_order` | `newest_first` | Mới → cũ, hoặc `oldest_first` |
| `max_jobs` | `100` | Tối đa job sẵn sàng được chọn, từ 1 đến 1000 |
| `max_api_attempts` | `100` | Tối đa lượt gọi API, gồm lỗi/retry, từ 1 đến 1000 |

Các bộ lọc được kết hợp bằng AND, kể cả khi chỉ định ID. Muốn chọn các ID rất cũ,
cần mở rộng khoảng ngày. `first_seen_at` giữ độ mới theo lần phát hiện đầu tiên;
fetch lại không làm job cũ được ưu tiên lên đầu. Khi ngày bằng nhau, ID là tiêu chí
phụ ổn định. Job thiếu ngày đã chọn được thống kê `missing_date` và bỏ qua;
số này nằm ngoài `matched` vì không thể xác định job có thuộc khoảng ngày hay không.

Ngày giờ không có offset được hiểu theo giờ Việt Nam (UTC+07:00). Ví dụ
`date_from="2026-09-01"`, `date_to="2026-10-01"` chọn trọn tháng 9.
Yêu cầu `date_from < date_to <= as_of`. Nếu chỉ nhập `date_to`, cửa sổ N ngày
được tính lùi từ ngày đó. Không dùng Airflow logical date làm đồng hồ hiện tại.

## Đọc dry run

- `matched`: job active, parse hợp lệ, khớp thời gian/nguồn/ID.
- `succeeded`: đã thành công cho cùng nội dung và phiên bản schema/prompt; bỏ qua.
- `failed_or_exhausted`: đã failed hoặc hết số attempts; không reset tự động.
- `processing`: đang xử lý; dry run không recover. Chạy thật chỉ recover công việc
  bị gián đoạn sau khi lấy được khóa chung của các worker.
- `retry_later`: còn quyền retry nhưng chưa đến giờ.
- `ready`: sẵn sàng xử lý theo queue; chưa đảm bảo provider còn quota.
- `eligible`: `ready + retry_later`.
- `selected`: lấy tối đa `max_jobs` từ `ready`, theo thứ tự đã chọn.
- `by_source`: phân bố từng nguồn; `sample`: 20 job đầu, kèm ID, tiêu đề, ngày và trạng thái.
- `providers`: key có cấu hình hay không, quota local còn lại trong 24 giờ,
  thời điểm hết cooldown, token ước tính cho nhóm được chọn và số input vượt
  ngân sách mỗi request của provider. Không hiển thị giá trị key.
- Khi bật Gemini `batch_size: 3`, `planned_requests` ước tính số request gộp,
  `selected_estimated_tokens` tính theo các nhóm, còn `single_job_estimated_tokens`
  là mức so sánh nếu chạy từng job. Đây là ước tính khi provider đó xử lý toàn bộ
  tập chọn; cooldown/quota còn lại có thể khiến nhóm thực tế thu nhỏ hoặc đổi provider.

Ước tính token cho từng provider là giả định provider đó xử lý cả nhóm, không
cộng các provider lại thành nhu cầu thực tế. Quota là ledger local, không phải
quota tài khoản đọc trực tiếp từ nhà cung cấp. Model có thể trả 429 sớm hơn.
Số `selected` không đảm bảo số thành công: quota, lỗi, retry và timeout vẫn áp dụng.

Dry run và chạy thật dùng cùng truy vấn chọn trên snapshot nhất quán. Preview
không lưu snapshot vào DB; lần chạy thật đọc lại, nên số lượng có thể thay đổi.
Trong một lần chạy thật, danh sách ID/hash/thứ tự được chốt sau khi preview;
worker kiểm tra lại job còn active và hash nội dung trước mỗi lượt gọi.
Job thay đổi giữa chừng bị bỏ qua, không tự thay bằng job ngoài danh sách đã chọn.

## CLI

```powershell
# Mặc định là dry run, 30 ngày gần nhất, mới nhất trước.
.venv/Scripts/python.exe -m joblake.main --phase enrich-backfill

# Preview khoảng ngày, nguồn và giới hạn riêng cho job/API.
.venv/Scripts/python.exe -m joblake.main --phase enrich-backfill --dry-run --date-from 2026-09-01 --date-to 2026-09-26 --sources topcv itviec --max-jobs 100 --max-api-attempts 100

# Chạy thật nhóm nhỏ sau khi xem preview; dùng lại mốc thời gian trong report.
.venv/Scripts/python.exe -m joblake.main --phase enrich-backfill --execute --date-from 2026-09-01 --date-to 2026-09-26 --sources topcv itviec --max-jobs 20 --max-api-attempts 20
```

Airflow chuyển toàn bộ tham số thành JSON qua environment rồi truyền dưới dạng
một argument có quote; không ghép giá trị người dùng thành lệnh shell.
CLI nhận cùng JSON bằng `--backfill-options`. `--dry-run` luôn ghi đè
`dry_run=false` trong JSON; `--execute` bật chạy thật một cách tường minh.

## Queue, triển khai và kiểm tra

- Dùng chung `core.job_enrichments`, lịch sử attempts, provider cooldown/quota,
  schema/prompt version và advisory lock với `joblake_enrichment`.
- DAG thông thường vẫn giữ nguyên cutoff. Việc đánh dấu `superseded` xét nội dung
  hiện tại/activity, không dựa vào việc job có nằm trong bộ lọc của DAG khác không.
- Bản backfill ban đầu không cần migration. Worker hỗ trợ gộp request hiện cần
  `alembic upgrade head` tới `0006_enrichment_batches` trước khi chạy. Không thay
  đổi cutoff đã lưu hay bật OpenRouter. Xem [chế độ gộp](enrichment-batches.md).
- Compose mount `dags/` và `src/`, nên scheduler đang chạy sẽ phát hiện DAG mới;
  task mới đọc code mới. Không cần rebuild image cho thay đổi này. Tránh thay code
  trong lúc worker cũ đang chạy; chờ worker đó kết thúc trước khi dùng backfill.
- Khi chạy tiếp, dùng lại khoảng ngày cũ nếu muốn xử lý cùng backlog. Cửa sổ mặc định
  tự trượt theo thời gian nên job quá 30 ngày sẽ cần tăng lookback hoặc chọn ngày tay.

```powershell
$env:JOBLAKE_TEST_ENRICHMENT='1'
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_enrichment*.py'
docker compose -f orchestration/airflow/compose.yaml exec airflow-scheduler python /opt/airflow/check_dag.py
```

SQL tests tạo database tạm riêng, dùng model giả lập, không gọi API thật.
`check_dag.py` kiểm tra import/config/render tham số trong Airflow thật và được CI gọi.
