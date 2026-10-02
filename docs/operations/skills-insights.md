# Skills, insights và bảo vệ truy cập

## Bản triển khai 2026-10-02

- Registry `joblake.skills/catalogue.json`: 221 kỹ năng, 288 cách viết, version `2026-10-02.1`. Giữ riêng Java/JavaScript, C/C++/C#, React/React Native; không suy luận từ chức danh. Nhãn chưa ánh xạ vẫn giữ trong kết quả enrichment gốc.
- `scripts/audit_skills.py` chỉ đọc local, xuất báo cáo vào `output/skills-audit.json` (không commit evidence). Mẫu được lấy tối đa 10 tin/nguồn; hiện có 82 mẫu, Devwork chỉ có 2 tin succeeded. Đây là mẫu chẩn đoán, chưa phải đánh giá ngẫu nhiên về độ chính xác của AI.
- Local: migration `30b2aa94d7aa` tạo `core.current_job_skills`, dựa trên current enrichment hợp lệ. Không thay attempts, prompt, model hay chạy AI backfill.
- Serving: generated STORED arrays `required_skill_keys` và `preferred_skill_keys`, GIN indexes; required thắng khi trùng preferred. Sync hiện hữu tự cập nhật projection khi input đổi. Chỉ dùng enrichment succeeded.
- RPC `search_jobs_v3` và `job_statistics_v1` dùng cùng predicate sinh từ `scripts/generate_skills_sql.py`. Search chạy trực tiếp để giữ index/order/LIMIT; aggregate dùng một snapshot và đếm DISTINCT posting trong mỗi nhóm.
- RPC và helpers là SECURITY INVOKER, search_path rỗng, không cấp PUBLIC EXECUTE. Web reader không có UPDATE. Security Advisor sau migration: không có cảnh báo.
- Web đóng gói cùng catalogue JSON, không cần request riêng cho 221 lựa chọn. Các nhãn chưa được registry hỗ trợ không tự biến thành lựa chọn.

## Ý nghĩa dữ liệu

Tại lần sync kiểm chứng: 6.992 tin, 526 succeeded (7,5%), 507 có kỹ năng trích xuất và 450 có kỹ năng bắt buộc đã chuẩn hóa. Số liệu thay đổi theo sync. Độ phủ required+preferred khác required-only; dashboard tính đúng phạm vi đang chọn. Không diễn giải tin thiếu dữ liệu thành không yêu cầu kỹ năng.

ANY khớp ít nhất một kỹ năng; ALL khớp tất cả, tối đa 10 key. Phạm vi mặc định required; có thể gộp preferred. Đây là phép lọc các mục được trích xuất, chưa mô hình hóa logic “A hoặc B” trong câu tuyển dụng. Trên mẫu có câu “Python hoặc C#”, cả hai có thể nằm trong danh sách required gốc; người xem cần đọc tin chi tiết.

Thống kê gồm top 15 kỹ năng, kinh nghiệm tối thiểu, cấp bậc, mode, địa điểm, nguồn; mỗi bucket đếm tin một lần. Mẫu số là tổng tin phù hợp, chưa gộp tin trùng khác nguồn. Cache aggregate 5 phút/100 khóa mỗi instance, không chứa page/sort trong key. Không tuyên bố phản ánh toàn thị trường.

## Kiểm chứng đã chạy

- 63 Python/SQL tests, có opt-in `JOBLAKE_TEST_SERVING=1`, chạy trên database local tạm. 34 web tests; lint, TypeScript và production build đạt.
- Reader production trong một transaction read-only repeatable-read: kết quả v2/v3 C++ giống nhau; ALL Python+SQL trong cả hai phạm vi có 29 tin, count dashboard khớp truy vấn.
- Mẫu 5 lần từ máy local đến Supabase: v2 72–97 ms, v3 72–74 ms, skill filter 73–76 ms, aggregate 242–270 ms; aggregate DB execution 168 ms. Đây là smoke benchmark, không phải kiểm thử tải quy mô lớn/SLA.
- Kiểm tra browser desktop và 360px: URL giữ bộ lọc khi chuyển tab, tìm alias Postgres ra PostgreSQL, submit ANY/ALL, scope và mobile không tràn ngang. Kiểm tra production được ghi ở HANDOFF của web.

## Chống cào theo lớp

1. Giữ database credential ở server, reader chỉ đọc serving; summary không trả mô tả dài, input/page size/offset đều giới hạn. CORS, robots.txt và giấu URL không phải cơ chế chống cào.
2. Vercel Bot Protection: theo dõi Log trước, sau đó Challenge nguồn không phải browser; verified bots theo cơ chế nền tảng. Không bật Attack Mode thường trực.
3. Một rate limit gộp theo IP: 120 request / 60 giây, fixed window, path `^(/|/jobs/[^/]+/?|/statistics/?)$`. Không tính `_next`, icon, robots. Chặn vượt ngưỡng bằng HTTP429 sau bước kiểm chứng. Cấu hình ở project firewall, không nằm trong Git và có hiệu lực không cần redeploy.
4. Cache + giới hạn pending/DB queue/deadline tiếp tục bảo vệ database khi có nhiều tổ hợp filter. Không bổ sung dịch vụ trả phí hoặc tài khoản bắt buộc.

Giới hạn: IP dùng chung có thể bị ảnh hưởng; bot dùng browser/proxy phân tán vẫn có thể lấy dữ liệu public. Theo dõi challenge/429/DB_BUSY, điều chỉnh ngưỡng dựa traffic thật. Bảo vệ giảm tốc độ/chi phí cào, không bảo đảm không sao chép được. Trạng thái bật thực tế ghi trong HANDOFF; mô tả mục tiêu ở trên không phải bằng chứng đã bật.

## Thay đổi registry và rollback

1. Review alias/evidence; cập nhật version và JSON gốc, chạy generator, đồng bộ JSON web, chạy parity tests. Không merge khái niệm rộng/hẹp chỉ vì giống tên.
2. Tạo migration mới bằng Supabase CLI, không sửa migration đã áp dụng. Đổi hàm IMMUTABLE không tự tính lại generated STORED cũ: migration version mới phải chủ động tính lại hàng hiện hữu (ví dụ cập nhật input về chính nó trong transaction có giới hạn), kiểm chứng coverage, rồi deploy web cùng registry. Không chạy enrichment AI để backfill alias.
3. Rollback web bằng deployment trước; giữ v1/v2 và additive schema để không mất dữ liệu. Không downgrade/drop generated columns khi web mới còn chạy.
4. Nếu chặn nhầm, điều chỉnh rule theo log và lưu lại lý do; thay đổi hạ mức bảo vệ cần tuân thủ quyền vận hành hiện hành. Không thêm system bypass diện rộng.

## Xác nhận production lúc 21:00, 2026-10-02 (GMT+7)

- Website production https://joblake-web.vercel.app đã phục vụ commit8c52f96: filters/tags, dashboard theo filter, chi tiết và return URL hoạt động. Preview Ready trước khi merge fast-forward main. Browser production không có console error/warn trong smoke test.
- Firewall đã publish: rule_job_lake_data_read_limit_vyDb84, fixed window120 request/60s/IP trên các đường đọc dữ liệu, action429; Bot Protection=Challenge. Không bật gói trả phí, Attack Mode hoặc system bypass. Counter theo region của Vercel, không phải quota toàn cầu xuyên vùng.
- Bằng chứng rate limit trên domain production, trước khi bật bot challenge:120 GET trả200, request121 trả429, dừng ngay; icon.svg vẫn200, tổng phép thử10,1 giây. Sau khi bật Bot Protection, request không có browser trả429 kèm x-vercel-mitigated:challenge và Security Checkpoint. Browser production reload vẫn hiển thị đúng29 tin Python+SQL ALL/cả hai phạm vi.
- Request không đăng nhập tới hostname preview theo redirect đến vercel.com/login (200), không phải nhận dữ liệu ứng dụng. Vì vậy phép thử chỉ đếm status200 trên preview trước đó không chứng minh rate limit lỗi. Standard Protection/Require Log In đang bật sẵn, không thay đổi; không tạo bypass token.
- Giới hạn còn lại: dữ liệu enrichment mới phủ khoảng7,5%; registry chưa bao phủ hết từ/certification; bot browser/proxy vẫn có thể thu thập public data. Đây không phải phép thử tải hoặc cam kết chống sao chép tuyệt đối.
- Schema serving đã áp dụng; local projection đã migrate; source pipeline và tài liệu ở workspace vẫn chưa commit/push vì repo có loạt sửa enrichment/batch có trước, bao gồm migration tiền nhiệm0006. Không đưa các thay đổi đó vào commit web.
