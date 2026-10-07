# Trang duyệt tài liệu RAG

Ngày: 2026-10-07. Trạng thái: hoàn tất bản local; server chạy cổng 8765.

## Phạm vi

Clone/chạy thử/đánh giá `Qyroven/scope-data-bot` tại commit `cb37446a00c6283cbb596df524885cfcb08a9fe7`; tích hợp parser và chunker vào ứng dụng local một người duyệt. Nguồn tham chiếu: hai hướng dẫn BTC/techstack trong `chung-khao/`. Không có ứng dụng sẵn trong repo đội.

## Các bước

1. Đọc đặc tả, kiểm upstream và dependencies.
2. [Triển khai và kiểm chứng](phase-01-review-workflow.md): nhập nguồn → staging → kiểm sơ bộ → duyệt → kho RAG và retrieval.
3. Kiểm hồi quy, kiểm UI thực, cập nhật hướng dẫn và báo cáo.

Kết quả: [33 tests đạt + smoke HTTP/UI](reports/app-validation.md), [đánh giá upstream](reports/scope-data-bot-review.md), [kiểm chứng upstream](reports/upstream-validation.md). OCR/BTC live và triển khai nhiều người dùng nằm ngoài bản local này.

## Nghiệm thu

- Nhập PDF có text, UTF-8 text/Markdown/HTML và URL public; giữ nguồn gốc/hash/vị trí.
- Điểm quy tắc có giải thích, không nhận là xác suất đúng; scan không OCR không được duyệt như đầy đủ.
- Chỉ bản được duyệt/đúng bộ tài liệu/đúng hiệu lực được truy hồi và export.
- Quyết định gắn revision; audit và dữ liệu bền qua restart; thu hồi loại khỏi retrieval.
- Chạy parser/chunker upstream thật, không gọi AI ngoài BTC, không dữ liệu giả trong giao diện.

## Giới hạn đã chọn

Local, single reviewer; SQLite FTS5 lexical retrieval. Chưa có bot hoặc hệ xác thực của sản phẩm để nối trực tiếp: cung cấp API evidence và export. Không bật embedding/LLM judge chưa kiểm qua BTC. Upstream chưa có license: clone riêng, không vendor/phân phối lại mã nguồn. Dữ liệu chạy nằm trên filesystem native trong ~/.local/share do đã tái hiện SQLite lỗi DBMOVED trên ổ exFAT chứa source.
