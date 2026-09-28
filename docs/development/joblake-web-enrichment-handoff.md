# Bàn giao AI enrichment cho joblake-web

Ngày bàn giao: 2026-09-26. Backend: `C:/Users/admin/Desktop/joblake`.
Frontend: `C:/Users/admin/Desktop/joblake-web`.

## Phạm vi và trạng thái

- Enrichment là phase riêng và DAG Airflow riêng `joblake_enrichment`; sync Supabase vẫn chạy được khi không chạy enrichment.
- Chỉ xử lý nội dung crawl mới/đổi từ `2026-09-26T00:00:00+07:00`. Nội dung cũ không đổi không được backfill. Chưa triển khai backfill; cần yêu cầu riêng của chủ project.
- Local migration đã áp dụng; các cột serving dưới đây đã được thêm vào Supabase. DDL này chưa được ghi vào lịch sử Supabase CLI migrations: không chạy blanket migration push để triển khai frontend.
- DAG chạy thủ công, mặc định dry_run=true, log ở task enrich_jobs. Lần kiểm tra dry-run đã thành công. Chưa chạy enrichment hàng loạt cho dữ liệu thật.
- Backend có queue/retry/quota, chỉ nhận một kết quả hợp lệ cho mỗi phiên bản nội dung. Frontend không gọi AI và không cần API key AI.
- Gemini/Groq đã qua mẫu synthetic. OpenRouter hiện cấu hình `nvidia/nemotron-3-super-120b-a12b:free`, strict JSON schema, reasoning tắt, output limit 4096. Chưa xác nhận extraction thành công trên model này: thử gọi thật gặp upstream 503 overload. Không coi OpenRouter là đã hoạt động ổn định.
- Thay đổi backend hiện chưa commit/push. Đọc code thực tế trước khi phụ thuộc vào phiên bản triển khai.

## Contract tại serving.jobs

Các cột mới là additive; các cột raw hiện hữu vẫn giữ nguyên.

| Cột | Kiểu PostgreSQL | Ý nghĩa |
| --- | --- | --- |
| skills_required | text[] nullable | Kỹ năng bắt buộc được nêu trong tin |
| skills_preferred | text[] nullable | Kỹ năng ưu tiên được nêu trong tin |
| experience_min_years | double precision nullable | Số năm kinh nghiệm tối thiểu |
| experience_max_years | double precision nullable | Số năm kinh nghiệm tối đa |
| seniority_levels | text[] nullable | intern, fresher, junior, middle, senior, lead, manager, director |
| work_mode | text nullable | onsite, hybrid, remote |
| employment_type | text nullable | full_time, part_time, internship, contract, temporary, freelance |
| enrichment_status | text not null default 'not_enriched' | Trạng thái dữ liệu enrichment phục vụ web |
| enriched_at | timestamptz nullable | Thời điểm enrichment |

`null` nghĩa là chưa biết/không được nêu, không phải 0 năm, không có kỹ năng hay onsite. Enrichment thành công vẫn có thể có nhiều trường null. Không tự điền giá trị suy đoán.

Backend lưu evidence và metadata provider/model ở local; chúng không thuộc contract UI. Kiểm tra `src/joblake/enrichment/serving.py` và view `core.current_job_enrichments` để đối chiếu chính xác phép chiếu trạng thái. Không đồng nhất trạng thái queue nội bộ với enum public của UI; xử lý trạng thái lạ an toàn.

## Công việc phía web

1. Kiểm tra query/types hiện tại, thêm các trường nullable và status/timestamp vào phép chọn dữ liệu chi tiết khi cần. Duy trì tương thích với tin cũ và fixture cũ.
2. Hiển thị kỹ năng bắt buộc/ưu tiên riêng khi có dữ liệu; hiển thị cấp bậc, hình thức làm việc, loại hợp đồng, kinh nghiệm khi có giá trị. Giữ thông tin raw làm fallback cho trường tương ứng khi thiếu dữ liệu enrich.
3. Tin chưa enrich vẫn hiển thị bình thường. Không hiển thị tên provider, quota, trạng thái retry hoặc cấu hình kỹ thuật trong luồng xem việc làm thông thường.
4. Không dùng kiểm tra truthy để hiển thị kinh nghiệm: 0 là giá trị hợp lệ. Hỗ trợ min-only, max-only, min=max, khoảng min/max và cả hai null.
5. Chỉ bổ sung bộ lọc khi query server/RPC hỗ trợ đúng, bao gồm count và pagination. Không lọc trên một trang đã tải rồi coi đó là toàn bộ kết quả. Cần nêu rõ chính sách cho dữ liệu unknown vì độ phủ enrichment ban đầu thấp.
6. Không gọi API AI từ web; không thêm các API key AI vào NEXT_PUBLIC hoặc bundle frontend.

## Lưu ý RPC tìm kiếm

`serving.search_jobs` hiện trả một tập cột cố định của contract cũ, chưa có các cột enrichment. Thêm cột vào bảng không tự thay đổi kết quả RPC. Search vector hiện hữu cũng không tự đưa kỹ năng AI vào index.

Nếu UI danh sách/bộ lọc cần dữ liệu mới, kiểm tra định nghĩa RPC đang triển khai và thống nhất thay đổi additive/versioned với backend. Không tùy tiện DROP RPC hoặc thay đổi return contract gây hỏng consumer. Giữ hành vi tìm kiếm prefix và các trường hợp C++, C#, .NET đã sửa trước đó. Count và danh sách phải dùng cùng điều kiện lọc.

## Kiểm thử frontend cần có

- Tin cũ không có enrichment vẫn render được như trước.
- Tin succeeded có đầy đủ trường; succeeded nhưng thiếu một phần hoặc tất cả trường.
- Status chưa biết/pending không làm hỏng trang hoặc hiển thị dữ liệu giả.
- Kinh nghiệm 0, min-only, max-only, min=max, khoảng min/max.
- Kỹ năng bắt buộc/ưu tiên, nhiều seniority, chuỗi dài và tiếng Việt.
- Tìm kiếm, count, pagination và bộ lọc cũ không regress.
- Chạy lint/typecheck/build và kiểm tra UI phù hợp với thay đổi thực tế.

## Nguồn đối chiếu

- `docs/operations/enrichment.md`: vận hành, quota, retry và contract.
- `configs/enrichment.yaml`: cấu hình hiện tại.
- `src/joblake/enrichment/schema.py`: schema, enum, validation.
- `src/joblake/enrichment/serving.py`: projection phục vụ sync.
- `src/joblake/sql/enrichment.sql`: eligibility và view local.
- `src/joblake/sql/serving_enrichment.sql`: DDL serving.
- `src/joblake/supabase_sync.py`: đồng bộ độc lập với enrichment.
- `orchestration/airflow/dags/joblake_enrichment.py`: DAG độc lập.

Lần bàn giao này là chuyển contract và công việc sang task web. Không bao gồm yêu cầu tự deploy production hoặc backfill dữ liệu cũ.

## Bộ lọc website v2 — 2026-09-27

- Người dùng đã chốt đợt1 filters và xác nhận riêng migration Supabase + điền first_seen_at. Migration thực tế 20260927020719_serving_search_v2 đã áp dụng; file local cùng version và SQL đóng gói serving_search_v2.sql.
- search_jobs_v1 giữ nguyên. v2 lọc đa nguồn/thành phố, kinh nghiệm tối thiểu, đa seniority/work_mode có unknown, thời gian và sort; giữ prefix/alias, LIMIT sau WHERE, không count tổng. Web giữ limit21/hiện20.
- JOB_COLUMNS/JOBS_QUERY sync thêm p.first_seen_at từ core.source_job_postings; SERVING_DDL/setup tạo cột và RPC mới. Nguồn posting giữ LEAST ngày thấy đầu khi crawl lại. Airflow compose bind-mount src, requirements cài editable; tác vụ mới dùng code này, không cần tạo DAG/schedule mới.
- Đã điền first_seen_at cho 6.883 tin hiện có bằng join id+canonical_url, chỉ cập nhật null hoặc ngày muộn hơn dữ liệu gốc. 3.347 tin thiếu posted_at, 0 tin thiếu cả hai mốc sau cập nhật. Không chạy full sync/crawl/AI backfill trong bước điền ngày.
- Thời gian filter/sort = coalesce(posted_at,first_seen_at). UI nhãn ngày dự phòng là Ghi nhận lần đầu, không coi là ngày đăng.
- Reader smoke test và burst có giới hạn đã qua; Security Advisor không lint, v2 SECURITY INVOKER, reader có EXECUTE, anon/authenticated không có. SQL test local v2/prefix/sync đã chạy trước migration (51 tests đạt); test mới bổ sung first_seen lặp sync được ghi riêng kết quả phía web.
- UI web chưa push/deploy. Không commit các thay đổi enrichment tồn tại sẵn bên joblake. Chi tiết cuối tại ../joblake-web/docs/FILTERS_CONTRACT.md.
