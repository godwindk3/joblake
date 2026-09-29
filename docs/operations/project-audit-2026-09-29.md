# Rà soát và tiêu chí chốt JobLake — 2026-09-29

## Phạm vi và độ chắc chắn

Rà soát source/config/DAG, tài liệu, log Airflow ngày 27–29/9 và snapshot health
gần nhất ngày 25/9. Run ngày 29/9 mới có log discovery tại thời điểm kiểm tra;
không coi việc chưa có log detail/parse là thất bại. Frontend nằm ở repo khác,
chưa được kiểm thử trong đợt này. Chưa xác minh trực tiếp DB, MinIO hoặc runtime
Airflow: Docker CLI không khả dụng trong môi trường kiểm tra.

330 test được phát hiện, 205 chạy thành công, 125 skipped. Các test tích hợp
DB bị bỏ qua không chứng minh storage đang hoạt động. Dùng Python bundled
3.12.14 và PYTHONPATH tới src cùng .venv/Lib/site-packages vì launcher .venv
không khởi động được Python gốc trong phiên này. `pip check` trong môi trường
kết hợp không báo dependency hỏng; CLI `--help` chạy được. Đây không phải
kiểm thử clean install hoặc kiểm thử image Docker. Log test: tmp/audit-tests.txt.

## Những việc cần chốt

| Ưu tiên | Bằng chứng | Việc làm / điều kiện hoàn tất |
| --- | --- | --- |
| P1 | data_health lỗi `KeyError: source` ngày 27/9 cả 3 attempts và ngày 28/9; snapshot mới nhất vẫn 25/9 | Code hiện tại đã bỏ qua config dùng chung không có source, có regression test. Chạy lại task trên code hiện tại và xác nhận JSON/Markdown mới đủ 9 nguồn. Không sửa lại lỗi đã được sửa. |
| P1 | TopCV parse ngày 28/9: processed=4, partial=1, rejected=3, status=suspicious, exit=0 | Đọc raw HTML của job 102984, 105928, 105976; phân biệt nội dung bị ẩn/thiếu với layout mới trước khi sửa parser. Chỉ reparse khi có bằng chứng; không bỏ validation để làm task xanh. Đếm backlog hiện tại bằng health mới. |
| P1 nếu muốn tự vận hành | Chín source DAG và sync đều schedule=None; chưa có cảnh báo chất lượng tự động | Chốt lịch ingestion, sync sau khi ingestion kết thúc, và kiểm tra freshness/parse rejection. Cần báo khi không có health mới hoặc nguồn vượt SLA; task xanh không thay thế kiểm tra dữ liệu. |
| P1 | Log runtime ghi cloakbrowser 0.5.10; pyproject.toml và constraints.txt pin 0.4.13 | Chốt phiên bản đã kiểm chứng, đồng bộ declaration/constraints/image, clean install và smoke test browser. Không nâng version chỉ vì thông báo update. |
| P2 | Source DAG không đặt execution_timeout; các request timeout không giới hạn tổng thời gian một phase | Đặt budget theo số trang/batch và thời gian quan sát, kiểm tra task timeout nhả source lock và không giữ pool vô hạn. |
| P2 | Raw cleanup scheduled ngày 28/9 chạy không có --apply; task-log cleanup DAG không còn trong repo | Quyết định retention thực thi hay chỉ preview, xác minh candidate trước khi bật apply. Log hiện khoảng 62 MiB/700 file, chưa phải sự cố dung lượng. Bao phủ thêm log maintenance/enrichment và retention health report khi cần. |
| P2 | Có backup phục vụ migration cũ nhưng chưa thấy lịch backup/restore định kỳ trong repo | Có backup PostgreSQL mới lưu ngoài máy chạy và thử restore vào DB riêng. Ghi rõ cách phục hồi config, raw cần giữ và browser state. |
| P2 | Không có .github workflow; 125 test bị skip | Thêm CI unit + DB integration trên DB kiểm thử, build/import DAG trong image thật. Không chạy test ghi dữ liệu trên production. |

## Lỗi đã hồi phục hoặc không nên đánh giá sai

- TopCV detail 28/9 attempt 1 bị Cloudflare chặn; attempt 2 completed/exit 0.
  Discovery cũng có 429 và retry. Đây là lỗi nguồn có hồi phục, khác với parse
  rejection còn tồn tại. Tôn trọng backoff và dừng nguồn khi bị chặn kéo dài.
- CareerLink 28/9 parse được 30/30 bản ghi partial, không rejected/failed.
  Snapshot 25/9 còn backlog 243 raw chưa có usable parse đã cũ; không dùng nó
  để khẳng định backlog hôm nay. Partial là dữ liệu được chấp nhận.
- Sync cuối ngày 28/9 lúc 01:52 UTC committed thành công, active_without_content=0.
  Tổng publishable trong log là 6.564. Đây là ảnh chụp lúc chạy, không phải live count.
- Enrichment 28/9 là dry-run: eligible_current=294; queue succeeded=266,
  retry_wait=2, failed=8. Ngày 27/9 có unsupported_evidence. Giữ validation;
  phân loại lỗi và retry có giới hạn, không lấy tỷ lệ này làm coverage toàn kho.
- Raw cleanup thủ công ngày 28/9 có --apply và exit 0; lần scheduled sau đó
  là dry-run. Không suy ra retention đã được tự động thực thi mỗi ngày.
- JobsGO HTTP 410 trong snapshot cũ cần được phân loại tin không còn tồn tại;
  không mặc định là parser hỏng. Missing salary/partial cũng không tự động là lỗi.

## Phạm vi hoàn tất đề xuất

Đóng băng tính năng mới và số nguồn. Ưu tiên health mới, phân loại TopCV,
đồng bộ môi trường chạy, rồi chốt vận hành và bằng chứng kiểm thử.

- [ ] Health mới sinh thành công, đủ 9 nguồn; không có backlog/stuck không giải thích được.
- [ ] TopCV rejected có nguyên nhân và cách xử lý được ghi lại; không có dữ liệu lỗi mới tăng âm thầm.
- [ ] Ba chu kỳ vận hành liên tiếp hoàn thành trong budget; retry/blocked được nhìn thấy.
- [ ] Nếu chọn chế độ tự động: dữ liệu serving được cập nhật sau ingestion và phát hiện được dữ liệu stale.
- [ ] Clean install/image build, DAG import và DB integration đều được xác minh.
- [ ] Restore backup thử nghiệm thành công; retention thực thi đúng chính sách đã chọn.
- [ ] Smoke test repo frontend: search prefix, lọc nguồn/thành phố, chi tiết job, thống kê và tin hết hạn.

Enrichment có thể giữ là tính năng tùy chọn để tránh kéo dài bản hoàn tất đầu tiên.
Không cần thêm nguồn, đổi framework hay refactor lớn để đạt các tiêu chí trên.
