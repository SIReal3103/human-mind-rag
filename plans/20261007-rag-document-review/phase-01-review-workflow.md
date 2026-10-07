# Triển khai luồng duyệt

## Context và files

- `../../agent-chatbot-btc-guide.md`, mục 9, 15, 18, 20.
- `../../cac-huong-phat-trien-san-pham-dua-vao-techstack.md`, vòng đời RAG.
- Tạo `../../rag-review/`: FastAPI, SQLite, UI static, parser adapter, tests, hướng dẫn chạy.
- Báo cáo tại `reports/`; giữ nguyên thay đổi có sẵn của người dùng.

## Yêu cầu/thực hiện

- Chạy loopback, chống request từ origin khác; nguồn không được thực thi như HTML/script.
- Parser worker có timeout; URL giới hạn byte/redirect và chặn IP private; nguồn gốc lưu riêng khỏi nội dung sửa.
- Metadata có source/version/collection và hiệu lực do reviewer nhập; không suy ngày upload là hiệu lực.
- Duyệt transaction nguyên bản và chunks; optimistic revision; bản approved bất biến, sửa cần revision mới.
- Điểm trích xuất dựa quy tắc và danh sách findings; không tự chứng minh factual correctness.

## Kiểm chứng

Upstream unit/lint; test ingestion thật; test state machine, stale review, isolation collection, hiệu lực, thu hồi, restart; smoke PDF/web/text và UI bằng browser.

## Rủi ro/rollback

FTS5 không phải semantic search; chưa kiểm OCR/BTC live. Local app chưa có tenant/auth. Gỡ module mới để rollback code; dữ liệu local trong thư mục bị Git ignore, không tự xóa dữ liệu khi rollback.
