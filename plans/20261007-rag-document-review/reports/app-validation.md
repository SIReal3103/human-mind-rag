# Kiểm chứng trang duyệt RAG

Ngày 2026-10-07. Source: `chung-khao/rag-review/`. Upstream pin: `cb37446a00c6283cbb596df524885cfcb08a9fe7`. Runtime Python 3.12.10, SQLite FTS5, dependency snapshot trong `requirements.lock.txt`.

## Kết quả cuối

Chạy tại thư mục ứng dụng, bằng `/path/to/user/.cache/rag-review-venv/bin/`:

| Kiểm | Kết quả |
|---|---|
| `python -m pytest -q` | 33 passed, 30 subtests passed, 13.69s |
| `ruff check .` | Đạt |
| `ruff format --check .` | 7 files đã đúng format (bao gồm code fence Markdown) |
| `node --check static/app.js` | Đạt |
| `bash -n setup.sh run.sh` | Đạt |

Còn 1 cảnh báo deprecation từ Starlette TestClient dùng httpx: khuyến nghị chuyển sang httpx2. Không suppress cảnh báo. Tests hiện dùng dependency đã pin và vẫn đạt. Chưa đo coverage phần trăm, load benchmark hay factual accuracy.

## Hành vi có kiểm

- Parser/chunker upstream thật: UTF-8, HTML bỏ script khỏi text, PDF hai trang, span đúng và locator trang thật. Sửa text bỏ locator trang cũ. Runtime worker không nhận key AI.
- DNS-pinned HTTPS, reject loopback/private/mapped IP, redirect recheck, giới hạn dung lượng/timeout. Live fetch example.com thành công; không quét/crawl site khác.
- Chỉ pending được sửa; stale revision/duplicate decision không publish lặp; các cảnh báo cần xác nhận, lỗi chặn không override.
- Pending/rejected/withdrawn không vào retrieval/export; collection và hiệu lực lọc trước LIMIT; dữ liệu/audit bền sau restart.
- Canonical date: `20260101` và `2026-W01-1` bị chặn 422; không còn bug so sánh lexical làm lọt tài liệu tương lai.
- PDF không có chữ được giữ pending cùng raw và lỗi chặn. PDF trộn trang chữ/ảnh có cảnh báo trang thiếu và partial; approve vẫn bị chặn dù acknowledge=true. Blank page không ảnh không bị đánh dấu thiếu. Không khẳng định phát hiện mọi ô bảng/hình ảnh bị mất.
- Reviewer thử đồng thời hai phiên bản chồng hiệu lực: một approved, một conflict, chỉ một bản được xuất bản.

## Smoke thực trên server cổng 8765

1. Trình duyệt nhập https://example.com vào bộ `validation`, xem HTML gốc dưới dạng text, xem score/findings, duyệt với ghi chú và tìm “documentation”. Kết quả trả một đoạn có source/version/locator. Không chạy script của HTML nguồn.
2. Upload file thật `agent-chatbot-btc-guide.md`: HTTP 201, 268 chunks, collection `team-guides`, **pending**, score 70/100 theo rules (chỉ dẫn và chuỗi giống secret trong code mẫu được gắn cờ, không khẳng định tài liệu chứa secret thực). Chưa duyệt tài liệu của người dùng.
3. Khởi động lại server: cả hai tài liệu còn nguyên. Kiểm HTTP mới: thu hồi nguồn thử nghiệm 200; `validation` search `no_evidence`, export 0; `team-guides` search `no_evidence`, export 0 vì chưa duyệt. Ngày không chuẩn trả422.
4. Ảnh bàn giao: [review-page.jpg](review-page.jpg), chụp trang thật sau restart/thu hồi.

Trình duyệt nhúng gặp lỗi điều khiển khi mở native `window.confirm` ở bước thu hồi. UI đã thay xác nhận native bằng cảnh báo trong trang/HTML dialog cho bản nháp; JS syntax đạt. Thu hồi được kiểm lại qua API thực. Kiểm tương tác đầy đủ của dialog mới và responsive trên thiết bị thật chưa hoàn tất trong phiên này; không coi các bước đó là browser E2E đã đạt. Các thao tác nhập web, xem nguồn, duyệt, tìm kiếm trước đó đã quan sát trực tiếp.

## Review và quyết định tích hợp

Review độc lập phát hiện bug ngày không canonical và PDF trộn scan; cả hai đã sửa cùng regression tests. Trong phạm vi local đã định, không tìm thêm approval bypass/SSRF/XSS có bằng chứng. Không suy luận từ kết quả này rằng có auth/tenant isolation cho public deployment.

Tái sử dụng **extract_document + spans/tokens** của upstream. Không sử dụng build/retrieve tự động của upstream vì chúng không thực thi workflow approval của ứng dụng. FTS5 là retrieval thực local; chưa tích hợp semantic embeddings, AI judge hoặc bot runtime (repo đội chưa có bot). API `/api/search` và snapshot `/api/export` là hợp đồng bàn giao cho bot.

## Storage và giới hạn

Thử CREATE TABLE + CREATE VIRTUAL TABLE FTS5 trên ổ chứa repo exFAT tái hiện `SQLITE_READONLY_DBMOVED`; cùng probe trên thư mục temp APFS đạt. Default data chuyển về `~/.local/share/delta-mind-rag-review/<workspace-id>/`. Source, tests và docs vẫn trong chung-khao. Không sửa file người dùng ngoài task, không commit/push.

Chưa gọi BTC live, chưa chạy Docling/OCR local, chưa thử nhiều người dùng/public deployment. Điểm kiểm sơ bộ chưa được calibration và không phải độ đúng của tài liệu. Upstream không có license declaration; chỉ clone riêng để chạy, không vendor source.
