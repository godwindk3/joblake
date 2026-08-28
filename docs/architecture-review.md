# JobLake - Review kiến trúc (2026-08)

Phạm vi: toàn bộ `src/joblake`, `configs/`, `tests/`, `docs/`.
Trạng thái khi review: branch `dev` @ `7ac4cf4`, 39/39 unittest pass.

---

## 1. Đánh giá tổng quan

Phần khung đang tốt hơn mức trung bình của một crawler tự viết:

- Tách bạch rõ: `JobSource` (biết về website) / `DiscoveryCrawler` +
  `IngestionPipeline` (không biết gì về website) / `RawStorage` /
  `StateStore` / `fetchers`. Thêm site mới không phải sửa pipeline.
- State machine chi tiết (`pending → fetching → validating → uploading
  → raw_ready`), có `fetch_attempts` bất biến để truy vết.
- Có cơ chế crash-recovery thật (`load_pending_uploads`,
  `recover_stale_fetches`) chứ không chỉ try/except.
- Validate raw HTML trước khi nhận vào `raw_objects` → không lưu rác
  vào Bronze.
- `parse_attempts` đã được thiết kế sẵn trong schema, nên phase parse
  cắm vào được ngay mà không phải migrate.

Vấn đề chính không nằm ở cấu trúc, mà ở **một vài đảm bảo bị hụt**,
**mô hình Bronze chưa immutable**, và **throughput**.

---

## 2. Bug / rủi ro đúng nghĩa (nên sửa trước)

### 2.1 Kiểm tra toàn vẹn với MinIO là no-op

`MinioRawStorage.stat_object()` nhận `expected_sha256` rồi **trả lại
chính giá trị đó**:

```python
return StoredObject(
    ...
    content_sha256=expected_sha256,   # không hề đọc lại object
)
```

Hệ quả:

- Trong `pipeline._crawl_detail`, câu
  `stored.content_sha256 != payload.content_sha256` **luôn False** →
  không bao giờ phát hiện sai lệch.
- `_audit_raw_objects` không bao giờ sinh ra `hash_mismatch`, chỉ phát
  hiện được `missing` và `size_mismatch`.
- `LocalRawStorage.stat_object` thì tính hash thật → hai backend có
  đảm bảo khác nhau, test local pass nhưng production không tương đương.

Cách sửa: so ETag khi object là single-part upload (ETag = MD5), hoặc
thêm `verify_hash: true` để audit tải object về và tính SHA-256 thật,
hoặc lưu sha256 vào user-metadata lúc `put_object` rồi đọc lại từ
`stat_object`. Rẻ nhất là cách thứ ba.

### 2.2 Job bị block sẽ chết vĩnh viễn

`claim_next_job` lọc `fetch_attempt_count < max_attempts`, mà
`fetch_attempt_count` tăng ngay khi claim. Khi bị Cloudflare chặn:

- `fail_attempt(attempt_status="blocked")` đặt `raw_status='blocked'`
  nhưng **không hoàn lại** attempt đã tiêu.
- Sau `detail_max_attempts` lần bị chặn (mặc định 3), URL đó không bao
  giờ được claim lại nữa, và nằm mãi ở `blocked` — không phải
  `permanent_error`, nên nhìn vào DB cũng không biết nó đã chết.

Điều tương tự xảy ra với `recover_stale_fetches`: mày bấm Ctrl+C giữa
chừng 3 lần là URL đó cũng cụt.

Cách sửa: tách bộ đếm — `fetch_attempt_count` chỉ tăng cho lỗi thuộc về
URL (404, HTML hỏng, validation fail), còn `blocked` / `InterruptedRun`
tăng cột riêng (`block_count`) hoặc rollback `fetch_attempt_count` về
giá trị trước khi claim. Đây là loại lỗi âm thầm làm hụt dữ liệu.

### 2.3 `ValidationResult.retryable` là field chết

Luôn được set `retryable=True` và không nơi nào đọc. Nghĩa là 404,
410, trang bị gỡ vẫn bị fetch lại đủ 3 lần với delay 10–25s mỗi lần.
Nên phân loại: lỗi vĩnh viễn (404/410/`unexpected_final_path` do
redirect về trang chủ) → `permanent_error` ngay, không retry.

### 2.4 Bronze đang bị ghi đè, không immutable

`_detail_url_hash()` = `sha256(source:url)` → object key cố định theo
URL. Crawl lại cùng URL sẽ **đè lên** object cũ, và `raw_objects` có
`UNIQUE(job_id)` nên mỗi job chỉ tồn tại đúng một bản raw.

Trái với chính nguyên tắc trong `architecture.md` ("Raw immutable
source data", "Every layer can be rebuilt from Bronze"), và làm mất
khả năng theo dõi biến động theo thời gian (lương đổi, deadline đổi,
tin bị gỡ) — vốn là thứ giá trị nhất của một job data lake.

Đề xuất key:

```
raw/detail/source=topdev/crawl_date=2026-08-10/<url_hash>/<sha256[:16]>.html
```

`raw_objects` chuyển sang nhiều bản ghi mỗi job, thêm cột
`is_current`, và `UNIQUE(job_id, content_sha256)` để không lưu trùng
khi nội dung không đổi (content-addressed → re-crawl mà HTML y hệt thì
chỉ cập nhật `last_seen_at`, không tốn thêm dung lượng).

### 2.5 Mất SQLite là mất luôn ý nghĩa của bucket

Object key là hash, MinIO chỉ được set `content_type`, không có
metadata nào khác. Nếu file `data/state/joblake.db` hỏng (nó đang nằm
local, không backup, `.gitignore` cả thư mục), thì bucket còn nguyên
nhưng không ai biết object nào ứng với URL nào.

Sửa rẻ: truyền `metadata={...}` vào `put_object` với `source`,
`job_url`, `fetched_at`, `sha256`, `transport`, `validation_version`,
`rendered`. Bucket khi đó tự mô tả được và rebuild lại state được.

### 2.6 Bronze lưu HTML đã bị biến đổi

`FetchResult.html` là `str`, lấy từ `response.text` (requests tự đoán
encoding) hoặc `page.content()` (DOM **sau khi JS chạy**), rồi
`.encode("utf-8")` khi lưu. Nghĩa là:

- Không giữ được bytes gốc → site trả `windows-1258`/charset lạ có thể
  bị hỏng ký tự ngay tại Bronze, không cứu được.
- Với transport browser, thứ lưu xuống không phải HTTP response mà là
  DOM đã render, nhưng **không có metadata nào ghi lại điều đó**.
  Parser sau này không biết file nào là raw, file nào là rendered.

Nên: `FetchResult` mang thêm `content: bytes` và `encoding`, lưu bytes
gốc; với browser thì đánh dấu `rendered=true` trong metadata.

---

## 3. Vấn đề thiết kế / vận hành

### 3.1 Throughput quá thấp so với mục tiêu data lake

Detail phase chạy tuần tự, mỗi job sleep 10–25s, `max_jobs_per_run:
20`. Tức một run TopDev thu được ~20 job trong ~7 phút. Muốn có vài
chục nghìn job thì không khả thi.

Hướng đi:

- `claim_next_job` đã dùng `BEGIN IMMEDIATE` nên **chạy nhiều process
  song song là an toàn** — chỉ cần bỏ giả định "một process một run".
  Cho phép `--workers N` hoặc chạy N process cùng config.
- Delay nên theo *domain* chứ theo *job*: một token bucket toàn cục cho
  mỗi host, thay vì sleep cứng sau mỗi job.
- Discovery cũng tuần tự từng page; các target độc lập nhau, hoàn toàn
  có thể chạy song song.

### 3.2 SQLite là trần cứng của kiến trúc

`architecture.md` vẽ Airflow + nhiều container, nhưng state nằm ở file
SQLite local. Khi crawler chạy trong container / nhiều máy thì mô hình
này vỡ.

Điểm tốt: `StateStore` đã là `Protocol`, nên thêm `PostgresStateStore`
là việc cơ học. Postgres còn cho `SELECT ... FOR UPDATE SKIP LOCKED`,
đúng bài cho hàng đợi nhiều worker. Chỉ có `create_state_store()` đang
khai báo trả về `SQLiteStateStore` và hard-fail provider khác — nên
sửa signature về `StateStore` để không khoá cứng.

### 3.3 Config không được validate

`load_config()` chỉ đọc YAML và check 2 thứ. Thiếu `detail.delay`,
`state.detail_max_attempts`, sai kiểu `pagination` … đều nổ giữa lúc
crawl, sau khi đã tốn thời gian và request. Trong khi `pydantic` đã nằm
sẵn trong `requirements.txt` mà **không được dùng ở bất kỳ đâu**.

Nên có `ConfigModel` bằng pydantic, fail-fast ngay lúc khởi động, và
đồng thời làm tài liệu sống cho schema config.

Ngoài ra `enabled: false` đang raise `ValueError` — semantics sai, một
source bị tắt nên được bỏ qua êm (exit 0), không phải lỗi.

### 3.4 Quan sát vận hành bằng `print()`

`pipeline.py` và `discovery.py` in bằng `print()`, chỉ `fetchers.py`
dùng `logging`. Không có level, không timestamp, không JSON, không
correlation id theo `run_id`. Đưa lên Airflow là không lọc nổi log.

Nên: `logging` toàn bộ, `--log-level`, format có `run_id`/`source`, và
xuất metrics cuối run (`crawl_success_rate`, `duplicate_rate`,
`validation_fail_rate` — chính là các metric `architecture.md` đã liệt
kê nhưng chưa ai tính).

### 3.5 Không có định danh nguồn ổn định

`jobs` định danh bằng `(source, url)`. URL đổi slug là thành job mới,
và cùng một tin đăng trên hai site không nối được với nhau. Dedup
(mục "10 Dedup Strategy" trong README) sẽ cần
`external_job_id` (TopDev có id trong URL `/detail-jobs/<id>-<slug>`)
và một `content_fingerprint`. Nên trích `external_id` ngay từ adapter
lúc discovery, rẻ hơn nhiều so với sửa sau.

### 3.6 Vệ sinh repo

- `requirements.txt` và `pyproject.toml` lệch nhau: `pydantic` chỉ có ở
  file đầu; `beautifulsoup4` được khai báo ở cả hai nhưng **chỉ dùng
  trong `topdev_url_using_requests.py` ở root**, không dùng trong
  `src/`.
- Các version pin trông không thực tế (`requests==2.34.2`,
  `beautifulsoup4==4.15.0`) — nên kiểm lại và pin bằng lock file.
- 8 script thử nghiệm nằm ở thư mục gốc lẫn với code thật → gom vào
  `scripts/` hoặc `sandbox/`.
- Không có dev-dependencies, không lint/format config, không CI. Test
  đang phải chạy bằng `python -m unittest discover -s tests` vì
  `pytest` còn chưa được cài trong venv.
- `architecture.md` mô tả Scrapy + Airflow + Polars, nhưng thực tế là
  crawler tự viết, chưa có orchestration. Nên tách rõ "hiện trạng" và
  "roadmap" để người mới không hiểu nhầm.

### 3.7 Chi tiết nhỏ

- `RequestsFetcher` không set User-Agent mặc định → gửi
  `python-requests/x.y`, mời gọi bị chặn. `configs/topdev.yaml` dùng
  `transport: requests` cho discovery mà không khai báo `user_agent`.
- `upsert_discovered_jobs` chạy 2 truy vấn/URL trong vòng lặp Python →
  nên gộp `INSERT ... ON CONFLICT DO UPDATE` + `executemany`.
- `LocalRawStorage` lưu `object_key = str(path)` (đường dẫn hệ thống)
  vào DB → state không portable giữa máy/OS.
- `SQLiteStateStore` mở/đóng connection cho từng thao tác (~5 lần mỗi
  job). Chưa đau, nhưng khi tăng worker thì nên giữ connection theo
  thread.
- Chưa có robots.txt / politeness policy tập trung — với một dự án
  crawl 4 site thương mại thì nên ghi rõ chính sách ngay từ đầu.

---

## 4. Thứ tự ưu tiên đề xuất

| Ưu tiên | Việc | Lý do |
| --- | --- | --- |
| P0 | Sửa 2.1 (verify SHA-256 thật) | Đảm bảo hiện đang giả |
| P0 | Sửa 2.2 (job blocked chết vĩnh viễn) | Mất dữ liệu âm thầm |
| P0 | Metadata cho object MinIO (2.5) | Rẻ, cứu được khi mất state |
| P1 | Bronze immutable + content-addressed (2.4) | Sửa sau sẽ phải migrate cả bucket |
| P1 | Validate config bằng pydantic (3.3) | Fail-fast, chặn lỗi vận hành |
| P1 | Thay `print` bằng `logging` + metrics (3.4) | Điều kiện cần để lên Airflow |
| P2 | Chạy song song nhiều worker (3.1) | Throughput |
| P2 | `PostgresStateStore` (3.2) | Bỏ trần SQLite |
| P2 | `external_id` từ adapter (3.5) | Dọn đường cho dedup |
| P3 | Dọn repo, CI, lint (3.6) | Chất lượng dài hạn |

Phase parse có thể làm song song với P0/P1 — thiết kế chi tiết ở
`docs/parsing-design.md`.
