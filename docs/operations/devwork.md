# Devwork

Nguồn `devwork` chỉ discovery tại `https://devwork.vn/viec-lam?page=N`.
Không đi theo trang kỹ năng, công ty hay tin gợi ý trên detail.
Discovery và detail dùng `requests`; các trang mẫu kiểm tra ngày 2026-09-18
trả HTML có nội dung đầy đủ mà không cần đăng nhập hoặc browser.

## Phân trang và dữ liệu

Nút phân trang là một cửa sổ trượt: trang 1 chỉ hiện 1–5, nhưng metadata
Nuxt lúc kiểm tra báo 7 trang. Adapter đọc `pagination.total_pages` bằng
cách giải mã đối số literal, không thực thi JavaScript. Nếu cấu trúc này
thay đổi, discovery báo lỗi phát hiện phân trang thay vì coi nút cuối đang
hiển thị là trang cuối. Giới hạn tự động: 200 trang.

URL detail phải thuộc Devwork và có dạng `/viec-lam/<id>/<slug>`.
Query và fragment được bỏ khi chuẩn hóa; kiểm tra detail từ chối redirect
sang job ID khác, trang danh sách, trang đăng nhập hoặc thiếu nội dung job.
Tên công ty nằm trong `.header-details h5`, có thể có hoặc không có link
đến hồ sơ công ty. Validator v2 và parser 1.0.1 nhận cả hai dạng. Bản v1
chỉ nhận link nên từ chối nhầm 49 detail trong lượt chạy đầu ngày 2026-09-18.

Parser lấy tiêu đề, công ty, mô tả, yêu cầu, quyền lợi, kỹ năng, địa điểm,
lương, kinh nghiệm, hình thức và hạn nộp từ HTML công khai.
Ngày đăng, lĩnh vực và nhóm nghề không hiển thị đáng tin cậy trong các vùng
HTML này nên để trống. Ba mẫu đạt chất lượng `partial` do thiếu
`domains_raw` và `categories_raw`; đây là trạng thái được hệ thống chấp nhận.
Không suy diễn mọi tin thành ngành IT vì danh sách có cả Sales và HR.

## Chạy

Config dùng MinIO/PostgreSQL chung với các nguồn hiện tại:

```powershell
python -m joblake.main --config configs/devwork.yaml --phase discovery --strict
python -m joblake.main --config configs/devwork.yaml --phase detail --strict
python -m joblake.main --config configs/devwork.yaml --phase parse --strict
```

DAG `joblake_devwork` có luồng `discovery -> detail -> parse`, pool
`joblake_serial`, chỉ chạy thủ công và mặc định paused. `detail.max_jobs_per_run`
là `null` (toàn bộ URL đủ điều kiện); có thể đặt giới hạn trước khi chạy thử.

Kiểm tra offline adapter, parser và luồng phân trang:

```powershell
python -m unittest discover -s tests -p test_devwork.py
```

Fixtures detail giữ các vùng HTML công khai cần thiết từ ba URL mẫu,
không chứa thông tin liên hệ hỗ trợ, script hay nội dung đăng nhập.
Kiểm tra Airflow thật dùng `orchestration/airflow/check_dag.py` trong
runtime Airflow theo hướng dẫn [Airflow](airflow-sources.md).

## Kết quả xác minh 2026-09-18

- Smoke test dùng `DiscoveryCrawler` và HTTP fetcher thật: 7 trang,
  138 URL duy nhất, không có target failed hoặc suspicious.
- Fetch và parse trực tiếp ba job `14252`, `14244`, `13181`: validation
  thành công, chất lượng `partial` với hai trường thiếu nêu trên.
- Bộ unittest: 161 ca, không lỗi, 23 ca hạ tầng được skip.
- DAG đã kiểm tra cú pháp; chưa kiểm tra import trong Airflow thật.
  Smoke test không ghi PostgreSQL/MinIO và không kích hoạt DAG.
