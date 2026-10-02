# Kế hoạch kỹ năng và thống kê theo bộ lọc

Ngày lập: 02/10/2026. Phạm vi: repository `joblake` và `joblake-web`.

Trạng thái: kế hoạch đề xuất theo yêu cầu người dùng; chưa triển khai runtime,
migration, backfill hoặc production. Các tên API/cột bên dưới là thiết kế dự kiến,
không phải hợp đồng đang tồn tại. Độ phủ và hiệu năng live chưa được đo ở lượt này.

## 1. Mục tiêu và phạm vi

Giúp người dùng tìm việc theo kỹ năng và hiểu yêu cầu của nhóm việc đang xem.
Chia thành hai mốc phát hành có thể dùng độc lập:

- **Mốc A — tìm việc theo kỹ năng:** chuẩn hóa kỹ năng, chọn nhiều kỹ năng,
  khớp một/tất cả, phân biệt bắt buộc/ưu tiên, tag trên danh sách và liên kết từ chi tiết.
- **Mốc B — thống kê theo bộ lọc:** tổng tin phù hợp, kỹ năng phổ biến,
  phân bố kinh nghiệm, cấp bậc, hình thức làm việc và độ phủ dữ liệu.

Chưa đưa vào hai mốc này: matching hồ sơ/CV, tài khoản, email thông báo, lương số,
chuẩn hóa công ty/gộp tin liên nguồn, xu hướng lịch sử, biểu đồ kỹ năng đi cùng nhau.
Các phần đó có thể nối tiếp sau khi nền kỹ năng và thống kê được kiểm chứng.

## 2. Hiện trạng đã đối chiếu

| Thành phần | Đang có | Khoảng trống |
| --- | --- | --- |
| Joblake enrichment | skills_required/preferred, evidence local, trạng thái và hash nội dung | Chưa có danh mục kỹ năng chuẩn và phép đo độ phủ cho tính năng này |
| Serving | Mảng kỹ năng enrichment và kỹ năng nguồn; một hàng/posting active | Chưa có khóa kỹ năng chuẩn dùng lọc |
| Search v2 | Nguồn, thành phố, kinh nghiệm, cấp bậc, work mode, ngày, sort | Không nhận bộ lọc kỹ năng; summary không trả kỹ năng |
| Web detail | Hiển thị bắt buộc/ưu tiên khi enrichment succeeded | Kỹ năng chưa liên kết đến bộ lọc |
| Web statistics | Tổng tin, địa điểm, nguồn trên toàn bộ serving | Không có bộ lọc hoặc thống kê enrichment |
| Dữ liệu lịch sử | Parse/enrichment history local | Serving không lưu lịch sử các tin đã bị loại |

Tham chiếu backend: [serving contract](serving-contract.md),
[enrichment](../operations/enrichment.md), [kiểm thử](testing.md).
Web: `src/lib/jobs.ts`, `query.ts`, `statistics-data.ts`, `components/filters.tsx`,
`components/job-row.tsx`, `app/jobs/[id]/page.tsx`, `docs/FILTERS_CONTRACT.md`.

## 3. Quyết định sản phẩm mặc định được đề xuất

### Lọc kỹ năng

- Chọn tối đa 10 kỹ năng qua ô tìm trong danh mục; hiển thị tên chuẩn.
- Mặc định **Có ít nhất một** kỹ năng; tùy chọn **Có đủ tất cả**.
- Phạm vi mặc định **Kỹ năng bắt buộc**; tùy chọn **Bắt buộc hoặc ưu tiên**.
- Trong phạm vi mở rộng, xét hợp của hai tập rồi mới áp dụng ANY/ALL.
- Các nhóm lọc khác vẫn AND với nhóm kỹ năng; giữ nguyên ngữ nghĩa v2.
- Không chọn kỹ năng = không hạn chế, kể cả tin thiếu kỹ năng.
- Có chọn kỹ năng = chỉ tin có dữ liệu chuẩn khớp mới đạt; null không có nghĩa
  nhà tuyển dụng không yêu cầu kỹ năng.
- Kỹ năng nguồn chỉ hiển thị theo nhãn nguồn, chưa trộn vào bộ lọc bắt buộc/ưu tiên.
  Không tự suy diễn phân loại từ tag nguồn hoặc từ khóa trong tên công ty.
- Chưa thay FTS/tính điểm từ khóa trong đợt này. Ô từ khóa và bộ lọc kỹ năng là
  hai điều kiện độc lập; mô tả điều này trong trợ giúp ngắn.

### Trình bày trên web

- Giữ bố cục hiện tại; thêm nhóm Kỹ năng ở vị trí dễ thấy trên desktop/mobile.
- Danh sách hiện tối đa 4 tag, ưu tiên kỹ năng đang chọn; phần còn lại là “+N”.
  Phân biệt nhãn bắt buộc/ưu tiên, không dùng màu làm tín hiệu duy nhất.
- Chi tiết giữ nguyên kỹ năng gốc để đối chiếu; kỹ năng có khóa chuẩn mới có link lọc.
- Gửi bộ lọc khi bấm Áp dụng, không query danh sách theo từng phím gõ.
- Thay bộ lọc về trang 1; search, phân trang, mở chi tiết/quay lại, Back/Forward,
  chip gỡ lựa chọn và reset đều bảo toàn trạng thái đúng.
- URL đề xuất: `skill=python&skill=sql&skill_match=all&skill_scope=required`.
  Danh sách kỹ năng dedup/sort để tạo cache key; mặc định được canonicalize.
- Kỹ năng sai/không còn trong danh mục không được âm thầm bỏ để mở rộng kết quả:
  hiển thị lỗi rõ ràng cùng thao tác xóa lựa chọn đó.

## 4. Giai đoạn 0 — audit dữ liệu, chưa gọi AI

**Joblake phụ trách.** Đọc local/serving bằng truy vấn chỉ đọc có giới hạn thời gian;
không chạy crawl, sync hoặc enrichment để “đo”. Báo cáo phải ghi thời điểm và
nguồn dữ liệu; so sánh local/serving để nhận ra serving chậm cập nhật.

Đầu ra: báo cáo có các bảng sau, toàn bộ và chia theo từng nguồn:

1. Tổng active posting, trạng thái enrichment, số tin có kỹ năng required/preferred,
   có tag nguồn, có kinh nghiệm/cấp bậc/mode hợp lệ; không nhầm succeeded với đủ dữ liệu.
2. Tần suất tên kỹ năng theo posting, alias ứng viên, chuỗi dài/không phải kỹ năng,
   giá trị mơ hồ và xung đột bắt buộc/ưu tiên sau chuẩn hóa.
3. Độ phủ theo thời gian ghi nhận và nguồn; chỉ ra ảnh hưởng của cutoff enrichment.
4. Bộ mẫu kiểm duyệt đề xuất: ít nhất 10 tin/nguồn nếu có, cộng mẫu có lỗi,
   alias, dấu câu và dữ liệu thiếu; ghi rõ giới hạn tính đại diện.
5. Baseline kích thước dữ liệu, độ trễ query và kích thước danh mục kỹ năng.

**Hoàn thành khi:** có số đo thật, danh sách alias ban đầu đã kiểm duyệt và quyết
định phạm vi danh mục. Nếu độ phủ thấp, báo cáo đề xuất backfill có số lượng/chi phí
riêng; không coi planning là lệnh chạy AI lịch sử. Độ phủ thấp không được che giấu
bằng việc trộn tag nguồn thành kỹ năng bắt buộc.

## 5. Giai đoạn 1 — chuẩn hóa kỹ năng ở Joblake

Thiết kế đề xuất: danh mục có khóa ổn định, tên hiển thị, alias và phiên bản;
thuật toán chuẩn hóa xác định, chạy lại được mà không gọi mô hình.

- Ví dụ: `Postgres` → `postgresql`, `Node.js` → `nodejs`, `C++` → `cplusplus`.
- Trim, chuẩn hóa Unicode và khoảng trắng, so alias không phân biệt hoa/thường;
  giữ dấu có ý nghĩa. Không xóa mọi dấu câu hoặc fuzzy-merge tự động.
- Không gộp Java/JavaScript, C/C++/C#, React/React Native, SQL/PostgreSQL.
- Alias chỉ gộp tên tương đương; không tự mở rộng họ công nghệ hoặc suy ra kỹ năng con.
- Chuỗi chưa có mapping giữ nguyên trong dữ liệu gốc và báo cáo chờ kiểm duyệt;
  không âm thầm mất dữ liệu hoặc trở thành lựa chọn chuẩn. Audit phải đo tỷ lệ này.
- Giữ nguyên result/evidence enrichment. Lưu projection chuẩn riêng với version
  để đổi taxonomy không làm mất bằng chứng hoặc cần chạy lại LLM.
- Chỉ chuẩn hóa kết quả succeeded khớp nội dung hiện tại. Khi JD đổi và chưa có
  enrichment mới, projection cũ phải bị loại khỏi lọc/thống kê ngay ở lần sync kế tiếp.
- Khi hai alias cùng khóa xuất hiện ở required và preferred, required thắng trong
  projection để tránh đếm đôi; ghi lại xung đột để kiểm tra, không sửa bằng chứng gốc.

Cấu trúc dự kiến: `src/joblake/skills/`, danh mục versioned trong `configs/`,
projection local qua migration Alembic; tên file/bảng chốt sau audit.
Script backfill projection có dry-run, batch giới hạn, tiến độ và khả năng tiếp tục;
không thay trạng thái attempt/quota enrichment.

**Hoàn thành khi:** kiểm thử alias/không gộp nhầm/null/hash nội dung đạt;
chạy lại ra cùng kết quả; đổi version tái tạo projection mà không gọi AI;
báo cáo độ phủ mapping và các trường hợp chưa xử lý được.

## 6. Giai đoạn 2 — serving và hợp đồng truy vấn

**Joblake sở hữu migration, sync và SQL; web sở hữu adapter/types.**

### Dữ liệu/API dự kiến

- Bổ sung khóa kỹ năng chuẩn required/preferred và normalization version trong
  serving; có danh mục khóa/tên/alias gọn phục vụ tìm lựa chọn.
- Danh mục và projection được xuất cùng một snapshot/transaction sync để không
  có job trỏ tới khóa mà web không biết. Giữ raw fields và API v1/v2.
- RPC `search_jobs_v3` nhận toàn bộ filter v2 cộng skills/match/scope; trả thêm
  summary kỹ năng gọn, không tải mô tả dài hoặc chạy query riêng cho từng job.
- Tách logic xác định tập posting phù hợp thành SQL dùng chung cho search và
  statistics. Không copy hai bộ WHERE rồi duy trì thủ công; chọn hình thức SQL
  sau EXPLAIN để không làm mất khả năng dùng index.
- Lọc ở database trước phân trang; giữ lấy 21/hiện 20 và hasMore.
- Giới hạn 10 kỹ năng, whitelist match/scope, kiểm tra khóa và loại bỏ trùng;
  validate ở cả SQL và parser web; query tham số hóa.
- Cân nhắc GIN cho tập kỹ năng dựa trên query plan thực tế; tránh chuẩn hóa chuỗi
  hoặc quét JSON enrichment trong từng request tìm việc.
- Giữ SECURITY INVOKER, RLS và role reader; chỉ thêm quyền đọc/execute cần thiết.
  Web không nhận metadata AI, evidence, credential hoặc quyền ghi.

### Kiểm thử hợp đồng bắt buộc

- ANY/ALL, required/required+preferred, skills rỗng, alias, kỹ năng lặp và ID sai.
- Một kỹ năng bắt buộc + một ưu tiên: ALL chỉ đạt trong phạm vi mở rộng.
- Kết hợp city/source/q/experience/seniority/mode/days; unknown như v2.
- Nhiều hơn 20 tin: match và đếm đúng toàn bộ tập trước pagination.
- Ngày fallback, prefix, C++/C#/.NET/Node.js và sort không hồi quy.
- Enrichment thất bại/cũ/null, normalization chưa chạy và đồng bộ lại nhiều lần.
- Sync loại posting inactive và projection lỗi thời; migration nâng cấp lẫn bootstrap.

**Hoàn thành khi:** SQL integration trên database dùng thử đạt, reader smoke test
đạt và hợp đồng phiên bản mới được ghi lại trước khi web phụ thuộc vào nó.

## 7. Giai đoạn 3 — web và phát hành mốc A

Các điểm sửa dự kiến trong `joblake-web`:

- `src/lib/types.ts`, `query.ts`, `jobs.ts`: filter, URL, projection và cache key.
- `components/filters.tsx`, `filter-state.tsx`: tìm/chọn kỹ năng, scope, ANY/ALL,
  hidden inputs, chip và mobile dialog.
- `components/job-row.tsx`, `app/jobs/[id]/page.tsx`: tag và link kỹ năng.
- Demo data và demo filtering giữ cùng ngữ nghĩa, không giả dữ liệu production.
- Tìm alias trên danh mục đã tải nếu kích thước audit cho phép; nếu quá lớn, dùng
  endpoint có giới hạn/debounce, không tải toàn bộ từ điển không giới hạn.

Kiểm tra browser desktop/mobile 360px: tìm nhiều kỹ năng, dữ liệu dài/thiếu,
zero results, đổi scope, ANY/ALL, pagination, detail/back, reset, bàn phím,
loading/error/retry và không tràn ngang. Kiểm tra bản preview rồi smoke production.

**Mốc A xong khi:** người dùng mở được URL bộ lọc chia sẻ, nhìn thấy lý do tin khớp
qua tag, thao tác đầy đủ trên mobile, và kết quả trùng với fixture/reader SQL.

## 8. Giai đoạn 4 — thống kê theo bộ lọc và phát hành mốc B

### Ngữ nghĩa đếm

- `/statistics` nhận cùng bộ lọc với danh sách; page/sort không ảnh hưởng aggregate.
  Hai tab chuyển qua lại giữ filter; có chip mô tả tập dữ liệu đang phân tích.
- Đơn vị là **tin đăng/posting**, chưa phải số vị trí tuyển dụng duy nhất. Tin đa
  nguồn có thể trùng; UI không gọi đây là số liệu toàn thị trường.
- Một tin đếm một lần trong mỗi kỹ năng/cấp bậc. Vì là đa nhãn, tổng tỷ lệ kỹ năng
  hoặc cấp bậc có thể vượt 100%; biểu đồ cột, không dùng pie cho các nhóm này.
- Top 15 kỹ năng theo scope đã chọn, đếm distinct posting, tie-break ổn định.
  Không cộng tần suất alias. Mẫu số phần trăm mặc định là tổng tin phù hợp,
  hiển thị rõ số tin có dữ liệu kỹ năng có thể sử dụng.
- Kinh nghiệm dùng các bucket mức tối thiểu của v2; mode dùng onsite/hybrid/remote;
  mọi phân bố có nhóm chưa rõ và tổng/mẫu số rõ ràng.
- Độ phủ tách: có enrichment thành công, có kỹ năng trích xuất, có khóa đã chuẩn
  hóa, có kinh nghiệm/cấp bậc/mode hợp lệ. Không biến giá trị thiếu thành 0/onsite.
- Có filter kỹ năng thì độ phủ kỹ năng trong kết quả thường là 100%; ghi đây là
  độ phủ của tập đã lọc. Không dùng con số đó để kết luận toàn bộ nguồn đủ dữ liệu.
- Bấm cột mở danh sách với giá trị của cột thay nhóm lọc tương ứng, giữ các nhóm
  khác và về trang 1. Ví dụ bấm SQL thay nhóm kỹ năng bằng SQL; tooltip mô tả rõ.
- Không thêm facet count động bên cạnh từng lựa chọn trong mốc này.

### Truy vấn và cache

- RPC aggregate dự kiến `job_statistics_v1`, dùng chung filter predicate với v3,
  tính tất cả biểu đồ trong một statement/snapshot; không lấy 20 kết quả để đếm,
  không kéo toàn bộ JD về Next.js và không tạo query cho mỗi cột biểu đồ.
- Trả total, các bucket, coverage và calculated_at; timestamp là lúc tính toán,
  không phải thời gian crawl/sync. Khi không có tin, trả total=0 và trạng thái rỗng.
- Danh sách và thống kê là các request khác nhau, có thể lệch tạm khi sync/cache;
  nghiệm thu tính bằng nhau trên cùng snapshot kiểm thử, không hứa đồng bộ tức thời.
- Cache theo filter canonical, bỏ page/sort; đề xuất TTL 5 phút, tối đa 100 kết quả
  cache/instance và giới hạn pending theo hạ tầng hiện có. Xác nhận lại bằng đo tải.
- Thống kê tải khi mở tab; không tự phát sinh aggregate cho mọi request danh sách.
  Giữ deadline/queue/retry của readDb, không tăng connection để che query chậm.

**Mốc B xong khi:** mỗi biểu đồ có đơn vị/mẫu số/unknown/time, tổng khớp truy vấn
kiểm chứng trên cùng dataset, chuyển qua danh sách giữ đúng ý nghĩa và lỗi thống kê
không chặn tính năng tìm việc.

## 9. Kiểm chứng, triển khai và rollback

1. Audit → taxonomy/projection → serving v3 → web mốc A → aggregate → web mốc B.
2. Unit và SQL integration cho chuẩn hóa/lọc/đếm/sync; dùng fixture biết trước
   kết quả, gồm job đa kỹ năng/cấp bậc/địa điểm để phát hiện nhân bản do join.
3. Web chạy tests, lint, typecheck/build theo scripts hiện có; browser preview
   với dữ liệu thật hoặc fixture được ghi rõ. Test lỗi DB, retry và cache key.
4. Đo cold/warm, filter rộng/hẹp, ANY/ALL, nhiều key khác nhau; ghi DB time,
   end-to-end time, lỗi/queue và EXPLAIN. Ngưỡng đề xuất trước triển khai:
   p95 search không tăng quá 20% so baseline cùng môi trường; aggregate DB p95
   dưới 1 giây trên tập đại diện, không timeout trong thử tải đã định nghĩa.
   Đây là mục tiêu nghiệm thu cần hiệu chỉnh sau audit, không phải SLA đã đo.
5. Migration additive trước, cập nhật pipeline/backfill projection xác định,
   sync và kiểm tra độ phủ/reader, rồi mới phát hành web phụ thuộc schema mới.
6. Sau mỗi mốc kiểm tra URL/chi tiết/unknown/bộ lọc cũ trên production, theo dõi
   slow query và DB_BUSY/DB_DEADLINE; ghi kết quả riêng từng môi trường.
7. Rollback web về phiên bản cũ, giữ v1/v2 và cột bổ sung; không DROP dữ liệu
   hoặc xóa evidence/history. Tắt đường tính năng mới nếu dữ liệu chưa sẵn sàng;
   không âm thầm bỏ filter kỹ năng khi RPC mới lỗi.
8. Cập nhật serving-contract ở Joblake và FILTERS_CONTRACT/PROJECT/HANDOFF ở web
   khi triển khai thực tế. Kiểm tra thay đổi sẵn có trước mỗi commit, không gom
   các sửa enrichment/backfill đang tồn tại vào commit tính năng này.

## 10. Thứ tự công việc có thể giao triển khai

| Việc | Repo chính | Phụ thuộc | Bằng chứng hoàn thành |
| --- | --- | --- | --- |
| A0: Báo cáo coverage và alias | joblake | Kết nối đọc dữ liệu | Báo cáo số đo, mẫu kiểm duyệt |
| A1: Registry + normalizer + projection | joblake | A0 | Unit tests, dry-run, mapping coverage |
| A2: Sync + search v3 + catalogue | joblake | A1 | SQL integration, reader smoke, EXPLAIN |
| A3: Bộ lọc/tag/link kỹ năng | joblake-web | A2 | URL tests, build, browser, mốc A |
| B1: Aggregate dùng chung predicate | joblake | A2 | Count/coverage fixtures, query benchmark |
| B2: Dashboard theo filter | joblake-web | A3, B1 | Drill-down, empty/unknown/error, mốc B |

Bước thực thi đầu tiên là A0. Sau báo cáo mới xác định cần backfill enrichment
bao nhiêu, danh mục lớn đến đâu và dự toán công sức còn lại; không ước lượng bằng
những con số dữ liệu lịch sử trong tài liệu bàn giao.

## 11. Kết quả triển khai và phần chống cào (2026-10-02)

Mốc A1/A2/A3/B1/B2 đã có code, migrations và kiểm thử. Audit A0 có số đo thật, danh sách unmapped và mẫu theo nguồn; chưa coi đó là đánh giá độ chính xác toàn bộ enrichment. Chi tiết kiến trúc, số đo, giới hạn dữ liệu, cập nhật registry và rollback nằm ở [runbook skills/insights](../operations/skills-insights.md).

Quyết định sau audit: dùng registry nhỏ 221 mục đóng gói vào web; local dùng view, serving dùng generated STORED arrays tương thích sync hiện hữu. Không cần AI backfill mới. Bộ lọc/aggregate dùng chung predicate sinh từ một generator; search inline để tránh overhead full-row helper. Ba migrations additive đã áp dụng lên serving trước khi phát hành web.

Bổ sung mốc C: Bot Protection + rate limit tại Vercel. Quy tắc gộp các đường đọc dữ liệu theo IP, 120 request/60 giây, bỏ static assets; theo dõi Log, kiểm chứng rồi bật HTTP429 và bot challenge. Tiêu chí: người dùng thường vẫn tìm/lọc/xem chi tiết được, static assets không bị quota này, traffic vượt ngưỡng bị hạn chế. Không coi robots.txt/CORS là bảo vệ, không hứa chống cào tuyệt đối, không thêm gói trả phí.

Đã đạt: 63 tests Python/SQL và 34 tests web; lint/build/TypeScript; kiểm chứng reader, count trên cùng snapshot và benchmark tương đương search v2. Trạng thái deployment và firewall cuối cùng ghi trong HANDOFF web; không dùng trạng thái kế hoạch để thay cho kiểm chứng production.

Mốc C đã xác nhận trên production: rate limit request121 trả429, Bot Protection challenge; browser vẫn truy cập được. Web8c52f96 đã deploy. Xem bằng chứng và giới hạn trong runbook, phần xác nhận production.
