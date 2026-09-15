# Diagnostics và các điểm tích tụ dữ liệu

## Cấu hình diagnostics

Đặt trong từng phần `discovery` hoặc `detail` của YAML:

```yaml
diagnostics_dir: data/state/diagnostics/vietnamworks/discovery
diagnostics_enabled: true
diagnostics_capture_success: false
diagnostics_retention_days: 7
diagnostics_max_captures: 100
```

Không có `diagnostics_dir` hoặc đặt `diagnostics_enabled: false` thì không
gắn listener, chụp ảnh, ghi bằng chứng hay chạy cleanup. `capture_success`
mặc định false; chỉ bật tạm khi cần so sánh lần thành công với lần lỗi.
VietnamWorks discovery trước đây bật success; nay discovery và detail đều
chỉ lưu lỗi. Các source chưa có directory vẫn không ghi diagnostics.

Cleanup chạy khi khởi tạo diagnostics và trước khi lưu bằng chứng: giữ tối
đa 100 bộ mỗi directory và bỏ bộ quá 7 ngày theo mtime. Đây là cleanup khi
crawl, không phải lịch nền: khi không chạy hoặc tắt diagnostics, file cũ vẫn
ở đó. TTL và số lượng phải dương. Không phải giới hạn cứng theo byte; HTML
và screenshot từng trang vẫn có thể lớn.

Chỉ xóa directory có tên timestamp/UUID do diagnostics sinh, chứa các file
`page.html`, `page.png`, `diagnostics.json`. Bỏ qua symlink, thư mục con và
file không nhận diện. Không đụng raw HTML nghiệp vụ, SQLite hay browser state.
File đã cleanup không có thùng rác. `latest_success.json` được bỏ khi hết hạn
hoặc bằng chứng nó trỏ tới không còn. Bộ success cũ được giữ đến TTL hoặc
giới hạn số lượng; đổi cấu hình không xóa ngay mọi success cũ.

Listener và tham chiếu request/page được giải phóng ở `close()`. Số request
được theo dõi vẫn giới hạn 300, API hoàn thành 30, event/console 50 mỗi loại.
API preview chỉ đọc JSON có Content-Length từ 1 đến 256 KiB và không nén;
thiếu chiều dài hoặc body nén thì chỉ giữ metadata. Giới hạn header là bộ
lọc thực dụng, không đảm bảo trần RAM nếu server khai báo sai chiều dài.

