# Human Mind — chạy thật từ nguồn đến tra cứu

2026-10-07. Backend local `http://localhost:8765`, upstream scope-data-bot khóa ở `cb37446a00c6283cbb596df524885cfcb08a9fe7`.

## Kết quả thực tế

| Bước | Kết quả |
| --- | --- |
| Tự tìm nguồn | Các phiên cũ gặp DuckDuckGo HTTP 202/challenge, không có nguồn; không vượt CAPTCHA. |
| Crawl URL trực tiếp | Thành công: 1 bài công khai, giới hạn 1 trang, độ sâu 0. |
| Parse/check | 2.549 ký tự, 4 đoạn preview; chất lượng trích xuất 100/100 là quy tắc kỹ thuật, không phải xác suất đúng. |
| Duyệt | Duyệt bộ demo sau đối chiếu nội dung với bài nguồn; actor ghi rõ Codex chạy thử theo yêu cầu. |
| Embedding | Lần đầu lỗi CA của Python; sau sửa HTTPS, OpenAI trả 401. Không có vector/index semantic thành công. |
| Tra cứu local | `trẻ em sinh tồn` trả 3 đoạn FTS5, tất cả thuộc đúng bản đã duyệt; đoạn đầu khớp nội dung hoạt động trẻ em. |
| Export local | 1 tài liệu approved, giữ bản nguồn, revision, chunks và audit. |

Nguồn: [Trải nghiệm du lịch xanh tại Vườn quốc gia Bù Gia Mập ở Bình Phước](https://nongthon.vietnamtourism.gov.vn/trai-nghiem-du-lich-xanh-tai-vuon-quoc-gia-bu-gia-map-o-binh-phuoc/), chuyên trang du lịch nông thôn của Cục Du lịch Quốc gia Việt Nam. Địa danh/số liệu giữ theo bài nguồn; không coi đây là xác nhận địa giới/số liệu hiện hành.

- Collection: `binh-phuoc-demo`.
- Crawl: `342278f2acd2425f93294f9429d1da36`.
- Document: `140cbc0d6810491a92c4248299dd2463`, revision 2, approved.
- Build lỗi TLS: `ed486a3477724670a1dbe94a3cb77d8d`.
- Build lỗi key 401: `e37a7d5309974f52a60d2719f63df905`.

Key OpenAI đã lưu khớp key trong `keys.rtf`, đúng nhóm ký tự, không có khoảng trắng; không ghi giá trị key vào báo cáo/log. Chỉ dùng OpenAI sau khi người dùng đồng ý lượt thử nhỏ; không chuyển sang Google hay thay BTC mặc định.

## Nguyên nhân và thay đổi

- Probe không key tái hiện HTTPS mặc định `CERTIFICATE_VERIFY_FAILED`. Context giữ CA hệ thống và nạp thêm certifi tới được endpoint OpenAI (401 dự kiến khi probe không xác thực). Sau đó build thực với key lưu vẫn 401: đây là lỗi xác thực riêng, chưa chứng minh key còn hiệu lực.
- Worker thêm HTTPS context, giữ xác minh hostname/chứng chỉ, chặn redirect và giới hạn đích upstream. Không sửa checkout scope-data-bot.
- Lỗi 401/403/429/mạng hiển thị gợi ý cụ thể; không ghi provider response body hoặc key. Trace build dùng gợi ý liên quan key/provider thay cho URL nguồn.
- Giao diện có hướng dẫn 4 bước; duyệt xong có nút sang cấu hình index, giữ đúng collection và BTC mặc định. Bước lỗi có nút sửa key và nhánh tra cứu local được ghi rõ là FTS5.
- Semantic evidence có thẻ đoạn nguồn/citation, JSON tải xuống, lưu lần tra gần nhất. GET và thao tác tải đều kiểm lại approval/hiệu lực trước khi trao dữ liệu. Phần này được kiểm gate offline; chưa có kết quả provider live để nghiệm thu toàn giao diện.

## Chạy tiếp với key hợp lệ

1. Mở **Cấu hình API key**, cập nhật OpenAI (hoặc BTC nếu chọn sử dụng BTC).
2. Vào **Crawl & RAG pipeline**. Trên thẻ Index `binh-phuoc-demo`, bấm **Kiểm tra cấu hình tạo index →**.
3. Kiểm tra collection `binh-phuoc-demo`, chọn provider vừa có key, bấm **Tạo index từ bản đã duyệt**. Không cần crawl hay duyệt lại bản demo.
4. Khi có trạng thái **Index đã tạo**, nhập: `Theo tài liệu, trẻ em có thể trải nghiệm những hoạt động nào tại Vườn quốc gia Bù Gia Mập?` rồi **Lấy evidence**.
5. Đối chiếu nguồn/citation và **Tải evidence JSON cho agent**. Câu trả lời LLM và bot runtime bên ngoài chưa được nối trong task này.

Để dùng ngay khi chưa sửa key: thẻ Index lỗi → **Tra cứu từ khóa không dùng key →** → nhập `trẻ em sinh tồn` → **Tìm trong kho**. Đây là nhánh local đã được chạy thật qua UI; không thay thế nghiệm thu semantic.

## Kiểm chứng

- 19 test tập trung: pipeline, adapter HTTPS/lỗi, trace đều qua.
- Toàn ứng dụng: **59 passed, 30 subtests passed**. Có 1 warning deprecation TestClient/httpx từ dependency; không có test bị bỏ để che lỗi.
- Ruff check/format và Node syntax check app.js/pipeline.js đều qua.
- Kiểm tra UI thật: nguồn đã duyệt → **Tiếp tục: tạo index** khôi phục collection/URL/giới hạn; provider vẫn BTC. Nhánh local khôi phục đúng collection và link export; truy vấn trả 3 đoạn thực.
- Kiểm tra API thật: toàn bộ kết quả tìm kiếm thuộc document demo; export đúng 1 bản approved.
- Review độc lập phát hiện link export chưa cập nhật collection và tải evidence từ màn hình cũ chưa recheck gate; cả hai đã sửa. Các test gate kiểm saved context bị chặn khi thu hồi.

Giới hạn còn lại: key hợp lệ là điều kiện để chạy semantic live; auto-discovery vẫn phụ thuộc DuckDuckGo; ví dụ chỉ một bài, không đại diện độ phủ kinh tế/văn hóa Bình Phước. Không có embedding giả, không coi đã hoàn tất semantic, không duyệt thay người phụ trách bộ chính thức.
