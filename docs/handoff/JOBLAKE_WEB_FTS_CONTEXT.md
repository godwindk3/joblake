# Hợp đồng tìm kiếm JobLake

Đã triển khai trên Supabase project `joblake` (`fidjbnoudkfebpfvkaux`), PostgreSQL
17.6, ngày 2026-09-22. Migration thực tế: `20260922011629_serving_search_prefix`.

## RPC không đổi

`serving.search_jobs(p_query text = '', p_source_code text = NULL,
p_city text = NULL, p_limit integer = 20, p_offset integer = 0)`.

Trả về `id, title, employer_name_raw, canonical_url, source_code, source_name,
location_cities, salary_raw, employment_type_raw, experience_raw, posted_at,
last_seen_at, score`. Không có total count trong RPC này. Limit 1–100, offset
0–10000, query tối đa 200 ký tự; input vượt giới hạn báo SQLSTATE `22023`.
NULL/chuỗi rỗng/chuỗi chỉ có dấu cách trả danh sách không lọc từ khóa; dấu câu
không tạo lexeme trả rỗng theo hành vi cũ. Bộ lọc source/city vẫn khớp chính xác.

## Quy tắc prefix

- Query thông thường: lexeme cuối được khớp tiền tố khi có ít nhất **3 ký tự
  sau chuẩn hóa**; lexeme trước vẫn khớp nguyên từ. `data eng` tương đương
  `data & eng:*`; `data enginee` tương đương `data & enginee:*`.
- `enginee` khớp engineer/engineering. `data en` vẫn yêu cầu nguyên từ `en`.
  `dat enginee` không tự mở rộng `dat` thành `data`.
- Dấu cách, tab và xuống dòng cuối query không làm thay đổi kết quả.
- Có dấu nháy kép, từ toán tử OR (không phân biệt hoa/thường), hoặc dấu trừ
  loại trừ: giữ toàn bộ `websearch_to_tsquery` cũ, không thêm prefix.
  Dấu gạch nối bên trong tên như `full-stack` không phải loại trừ.
- Phần trước nhóm ký tự cuối phân cách bằng whitespace vẫn dùng parser cũ.
  Nhóm cuối được PostgreSQL `ts_debug(simple)` phân tích; compound có gạch nối
  dùng các thành phần (bỏ token compound nguyên khối): `full-sta` →
  `full & sta:*`, `full-stack dev` giữ tên full-stack ở phần trước.
  Nếu nhóm cuối chỉ chứa dấu câu hoặc lexeme cuối ngắn hơn ngưỡng, giữ query cũ.
- Giữ nguyên simple/unaccent, tiếng Việt có/không dấu và alias C++ → cplusplus,
  C# → csharp, .NET → dotnet, Node.js → nodejs. Ngưỡng xét trên alias đã chuẩn hóa.
- Chưa có typo correction, infix search hay autocomplete.

Điểm vẫn là `ts_rank(search_vector, q)` với **cùng q dùng để lọc**. Title/skills
có trọng số A, employer/categories B; không tìm trong description. Sắp xếp
`score DESC, posted_at DESC NULLS LAST, id DESC`. Không thêm điểm thưởng exact:
`data engineer` cũng khớp engineering; fixture kiểm tra engineering có thể đồng
điểm và được sắp theo ngày/id. Dữ liệu thật tăng từ 137 lên 145 kết quả; top 10
có một tin tên “Data Engineering”, các kết quả vẫn thuộc nhóm liên quan.

## Cài đặt, nâng cấp và rollback

- SQL v1 tại `src/joblake/sql/serving_search_v1.sql` được giữ nguyên làm baseline.
- Cài mới qua `supabase-setup`: tạo schema, chạy v1 rồi
  `src/joblake/sql/serving_search_prefix.sql` trong cùng transaction.
- Nâng cấp schema đã có v1: chỉ chạy
  `supabase/migrations/20260922011629_serving_search_prefix.sql` trong transaction.
  File này giống hệt SQL prefix đóng gói. Tên file đã đồng bộ version do MCP
  ghi trên remote; file ban đầu được tạo bằng `supabase migration new`.
- Thư mục Supabase migrations chỉ chứa bản nâng cấp này, không phải toàn bộ
  bootstrap/history cũ; không dùng riêng nó để dựng database rỗng.
- Rollback: chạy `src/joblake/sql/serving_search_prefix_rollback.sql` trong
  transaction. Khôi phục đúng body hàm trước nâng cấp, giữ grants bằng
  `CREATE OR REPLACE`. Khi rollback production, ghi một migration bù mới;
  không xóa bản migration đã áp dụng khỏi lịch sử.

Migration dùng advisory lock hiện có, lock timeout 10 giây, statement timeout
120 giây. Không đổi bảng, trigger, RLS, sync hay index; không crawl/sync/backfill.
`SECURITY INVOKER`, search_path rỗng, ACL và hai policy SELECT của
`joblake_web_reader` không đổi. Reader gọi RPC thành công, không có INSERT,
UPDATE, DELETE, TRUNCATE trên jobs/sources. Security Advisor không có lint trước
và sau triển khai. Cài mới vẫn cần cấu hình reader/policy riêng như trước.

## Kiểm chứng

31 test `test_supabase*.py` qua trên PostgreSQL local 16.15 trong database dùng
một lần, trước khi áp dụng remote. Fixture gồm prefix, từ trước exact, token
ngắn, tiếng Việt, alias, cú pháp, gạch nối, ký tự đặc biệt, giới hạn input,
ranking A/B, NULL posted_at, tie-break id, source/city, trang không lặp,
rollback → upgrade → upgrade lặp và giữ ACL/SECURITY INVOKER. Role test dùng
tên ngẫu nhiên, rollback cả role/grants/policy; không sửa role thật trên local.

Sau triển khai: 22 kiểm tra read-only bằng kết nối `joblake_web_reader` thực tế
của website đều qua, bao gồm phân trang đủ 162 hàng không lặp trong snapshot
repeatable-read, filter source/city và so sánh RPC với predicate/score mong đợi.

EXPLAIN ANALYZE BUFFERS trên 6.387 hàng, dưới quyền reader, warm-up một lần rồi
đo ba mẫu. Số dưới đây là trung vị mili giây phía database, không gồm mạng/UI:

| Query | Số hàng cũ → prefix | SELECT cũ → prefix | RPC trước → sau |
| --- | ---: | ---: | ---: |
| data eng | 0 → 162 | 0,065 → 0,884 | 0,491 → 1,981 |
| data enginee | 0 → 145 | 0,060 → 0,762 | 0,425 → 1,749 |
| data engineer | 137 → 145 | 0,585 → 0,796 | 0,992 → 1,749 |
| dev | 26 → 1.080 | 0,190 → 2,928 | 0,543 → 3,767 |

Các SELECT prefix đều dùng Bitmap Index Scan trên `jobs_search_vector_idx`.
Đo cả SELECT bên trong vì EXPLAIN RPC PL/pgSQL chỉ hiện Function Scan. Đây là
phép đo mẫu, không phải load test đồng thời hay cam kết latency. Chưa có bằng
chứng cần index mới.

Chi tiết: [trước](search-prefix-before.json), [sau](search-prefix-after.json),
[smoke](search-prefix-smoke.json). Chạy lại từ root joblake:

```powershell
$env:JOBLAKE_TEST_SERVING = '1'
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_supabase*.py' -v
.venv/Scripts/python.exe scripts/benchmark_search_prefix.py --target remote --reader-env ../joblake-web/.env.local --output tmp/search-plans.json
.venv/Scripts/python.exe scripts/verify_search_prefix.py --reader-env ../joblake-web/.env.local --output tmp/search-smoke.json
```

## Bàn giao website

Giữ cách gọi RPC. Kiểm tra search `data eng`/`data enginee`, filter và chuyển
trang trên UI; cập nhật hướng dẫn gợi ý: “Có thể nhập phần đầu của từ cuối từ
3 ký tự, ví dụ data eng. Dùng dấu nháy kép để tìm cụm từ chính xác.” Nêu rõ
OR/loại trừ giữ cú pháp cũ. Cache website có TTL **5 phút**: chờ hết TTL hoặc
revalidate trước khi kết luận truy vấn cũ vẫn lỗi. Kiểm tra DB ở trên bỏ qua
cache và chưa thay thế kiểm tra UI/deployment của website.

## Tài liệu đối chiếu

- [PostgreSQL 17: prefix, websearch và ranking](https://www.postgresql.org/docs/17/textsearch-controls.html)
- [PostgreSQL 17: ts_debug](https://www.postgresql.org/docs/17/textsearch-debugging.html)
- [PostgreSQL 16: môi trường test local](https://www.postgresql.org/docs/16/textsearch-controls.html)
- [Supabase changelog](https://supabase.com/changelog): đã kiểm tra trước triển khai;
  không thấy thay đổi liên quan yêu cầu sửa hợp đồng PostgreSQL FTS này.
