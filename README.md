# Human Mind — Duyệt tài liệu RAG

Giao diện local cho **scope → tự tìm nguồn → crawl/parse/check → duyệt → chunk/embedding/index → evidence**. Dùng [scope-data-bot](https://github.com/Qyroven/scope-data-bot) khóa tại `cb37446a00c6283cbb596df524885cfcb08a9fe7`. Không sửa source upstream.

Từ bản cấu hình API gốc, crawl/build/query gọi trực tiếp hàm upstream, không cài `StageRouter`, không chọn model từng bước, không sửa prompt/schema và không tự sửa assessment. UI chỉ hiển thị cấu hình API đang có. Human Mind vẫn quản lý HITL/tự duyệt, snapshot approved, key store riêng, trace và gate thu hồi.

Xem [hướng dẫn agent](AGENT-GUIDE.md) để vận hành và phân biệt các phần bổ sung.

## Cài và chạy

Cần Python 3.12, Git, SQLite FTS5; mạng để cài dependencies/tokenizer lần đầu.

```bash
git clone https://github.com/SIReal3103/human-mind-rag.git
cd human-mind-rag
bash setup.sh
# Tạo cấu hình upstream nếu chưa có; không ghi đè cấu hình đã có:
test -f .runtime/scope-data-bot/.env.local || cp .runtime/scope-data-bot/.env.example .runtime/scope-data-bot/.env.local
# Sửa .runtime/scope-data-bot/.env.local trên máy: profile/model/key theo upstream.
bash run.sh
```

Mở `http://127.0.0.1:8765/`. `setup.sh` clone riêng đúng commit, không chép source upstream vào repo này. Upstream chưa khai báo license; không tự thêm license cho source đó.

Có thể dùng `SCOPE_BOT_PATH`, `RAG_REVIEW_PYTHON`, `RAG_REVIEW_VENV`, `RAG_REVIEW_PORT`, `RAG_REVIEW_DATA`. Nếu đặt `SCOPE_BOT_PATH`, sửa `.env.local` trong chính checkout đó. Khởi động lại server khi thay environment; `.env.local` được đọc lại khi kiểm cấu hình/bắt đầu bước.

## API: đúng cấu hình scope-data-bot

`gateway.setting()` gốc quyết định theo **environment → scope-data-bot/.env.local → mặc định**. UI không tự chọn hoặc ghi đè các giá trị này.

| Cấu hình | OpenAI | BTC |
|---|---|---|
| `AI_PROVIDER` | `openai` (mặc định upstream) | `btc` |
| Key | `OPENAI_API_KEY`, sau đó alias legacy `THUCCHIEN_API_KEY` | `BTC_API_KEY` |
| Model text/search mặc định | `OPENAI_SEARCH_MODEL=gpt-4.1-mini` | `BTC_TEXT_MODEL=gpt-6-luna` |
| Embedding mặc định | `OPENAI_EMBEDDING_MODEL=text-embedding-3-small` | `BTC_EMBEDDING_MODEL=text-multilingual-embedding-002` |
| Chiều mặc định nếu không đặt | 1536 | 768 |
| Text/search endpoint | `https://api.openai.com/v1/responses` | `https://api.thucchien.ai/responses` |
| Embedding endpoint | `https://api.openai.com/v1/embeddings` | `https://api.thucchien.ai/embeddings` |

Planner/check/query gate/rerank dùng cùng text model. Search dùng tool `web_search` và payload gốc; embedding dùng implementation/payload/validation/batch của upstream. `EMBEDDING_DIMENSIONS` nếu đặt sẽ ưu tiên hơn chiều mặc định theo provider: đổi provider phải kiểm cả biến này.

BTC vẫn kiểm `BTC_STRUCTURED_VERIFIED`, `BTC_SEARCH_VERIFIED`, `BTC_EMBEDDING_VERIFIED`, `BTC_EMBEDDING_BATCH_VERIFIED`. Chỉ bật sau khi thực sự kiểm đúng model/endpoint/protocol. UI hiển thị cờ được cấu hình, không coi cờ là bằng chứng đã smoke-test. Không tự fallback sang provider khác.

**Chú ý alias:** `THUCCHIEN_API_KEY` được upstream coi là alias OpenAI legacy, không tự biến thành profile BTC. Nếu thiếu `OPENAI_API_KEY` nhưng environment có alias này, UI sẽ ghi rõ đang dùng nó. `configured=true` chỉ nghĩa có giá trị, không chứng minh key hợp lệ. Không in key ra terminal/log/chat.

**Kho key trong Cấu hình API key của Human Mind là kho riêng, không được dùng cho pipeline gốc.** Lưu/thay/reset tại UI không sửa environment hoặc `.env.local` upstream. Chỉ giữ chức năng này cho người dùng đã lưu key và các tích hợp khác; UI có thông báo phân biệt. Không tự chuyển key giữa hai kho. Key app lưu plaintext với quyền file 0600/thư mục 0700, chưa có Keychain; reset không thu hồi key ở provider.

## Thao tác UI

1. Mở **Crawl & RAG pipeline** → **Tạo phiên mới**. Nhập scope và collection; dùng collection mới khi cần tách corpus cũ.
2. Đọc khối **API đang dùng · cấu hình scope-data-bot gốc**: provider, text model, embedding/chiều, endpoints, tên biến và nguồn key. Bấm **Đọc lại cấu hình upstream** sau khi sửa file. Không có dropdown API/model.
3. Chọn giới hạn crawl. Mặc định 12 trang/sâu 1/5 nguồn. Sâu 0 lấy URL đầu, 1 theo thêm một lớp link, 2 thêm hai lớp. Số trang không phải số API calls hay hạn mức tiền.
4. Có thể bật **Tự động duyệt tài liệu đủ điều kiện**. Bấm **Bắt đầu crawl**, theo dõi trace. Không cần nhập URL; upstream tự tìm.
5. Mở hàng chờ đúng phiên; đối chiếu bản gốc, trích xuất, cảnh báo, sửa bản pending, ghi người duyệt rồi approve/reject. Có thể áp chính sách tự duyệt cho phiên đã hoàn tất.
6. **Tạo index từ bản đã duyệt**: snapshot lấy tất cả approved còn hiệu lực trong collection, không chỉ một phiên crawl. Pending không vào embedding/index.
7. Khi ready, nhập câu hỏi → **Lấy evidence** → đọc nguồn → **Tải evidence JSON cho agent**. Query dùng API gốc; không có model riêng cho lần tra.

Index lưu cấu hình API tại lúc build. Nếu provider/model/chiều/endpoints/capability config đã đổi, khôi phục cấu hình hoặc build lại; không trộn vector khác profile. Index adapter cũ chỉ xem/tải evidence đã lưu nếu approval gate còn hợp lệ; muốn tra mới phải build lại theo API gốc.

Tạo phiên mới giữ lịch sử, tài liệu và key. Không có job resume tự động/vô hạn. Job có owner PID đã chết được đánh dấu interrupted; job còn chủ sống hoặc legacy thiếu PID không bị suy diễn là đã dừng. Phiên UI cũ chỉ refresh CSRF một lần khi server trả đúng lỗi phiên nội bộ, không dùng để retry lỗi provider.

## HITL, tự duyệt và nhập tay

Thêm PDF/TXT/MD/HTML, dán text hoặc URL công khai tại **Thêm tài liệu**; đây là luồng nhập riêng, không thay seed của pipeline. Giới hạn 10 MB/600.000 ký tự. Parser/chunker local; text UTF-8; bản gốc bất biến. Native PDF giữ trang thật, scan/partial cần OCR hoặc nội dung đã đối chiếu. Docling/OCR của ứng dụng chưa nghiệm thu; xem setup parser ở upstream.

Điểm chất lượng trích xuất là quy tắc 0–100, không phải xác suất đúng. Có findings về parse rỗng/partial, ký tự lỗi, nội dung ngắn, trùng nguồn, thiếu hiệu lực, dấu hiệu secret/prompt injection. Không bảo đảm phát hiện mọi sai sót. `factual_confidence=unverified`.

Tự duyệt `auto-review-v1` mặc định tắt. Cần đồng thời: pending revision 1 chưa sửa; có chunks; score >=90; không warning/error; nguồn web có URL; assessment status review, subject_match=true, geography_match=true nếu có country gate; có evidence quotes với verification `model_assessed_quotes_checked_not_fact_verified`; không partial/truncated. Bản không đạt giữ pending và lý do. Audit phân biệt automatic/manual, không coi tự duyệt là người đã xác minh sự thật.

Approve có revision/hash/audit và kiểm cảnh báo trong transaction. Reject cần lý do, có thể reopen. Approved bất biến; thay nội dung bằng phiên bản mới. Thu hồi nguồn và thay tập approved làm index cũ bị chặn. Tên reviewer chỉ là nhãn local, chưa có đăng nhập xác thực danh tính. Hiệu lực lấy từ metadata đã kiểm, không dùng ngày upload làm ngày có hiệu lực.

## Lỗi và tiếp tục

- **401:** key của provider upstream bị từ chối. Đọc tên biến/nguồn key trên UI; thay đúng environment/.env.local rồi chạy lượt mới. Key UI riêng không sửa lỗi này.
- **403 provider / 402 / 429:** kiểm quyền model, billing/quota/rate limit. Không tự đổi provider.
- **CAPABILITY_UNVERIFIED:** BTC gate gốc chưa mở; không tự bật để vượt lỗi.
- **invalid output / planner năm sai:** lỗi đầu ra model/hợp đồng, không phải kết luận key hỏng; đọc trace và scope. Giữ prompt/validator gốc, không có lượt sửa assessment riêng của Human Mind.
- **HTTP/TLS/robots/trang chặn:** lỗi nguồn; crawler gốc tiếp tục nguồn khác trong budget. Không tắt TLS/vượt chặn.
- **0 tài liệu:** chưa thu thập được dữ liệu để duyệt; hoàn tất job không phải ingestion thành công.
- **Config/index thay đổi:** build lại; worker kiểm lại config trước khi gọi upstream để tránh UI hiển thị một kiểu nhưng chạy kiểu khác.

Lịch sử lỗi không tự biến mất khi thay key. **Thử lại bước này** tạo lượt mới với cấu hình upstream hiện tại. Xem trace nguồn và lỗi đã lọc thông tin nhạy cảm; không coi thiếu adapter API-event log là không có lời gọi — native trace/receipts nằm trong artifacts upstream.

## API cho agent

Mutation cần `X-CSRF-Token` từ `GET /api/config` và same-origin khi dùng browser. Các API chỉ bind local, chưa có tenant ACL.

- `GET /api/upstream/config`: cấu hình chỉ đọc, không gọi AI/không trả giá trị key.
- `POST /api/pipeline`: `{action:"crawl"|"build", scope, collection, max_sources?, max_pages?, max_depth?, auto_approve?}`. Không nhận `provider`, `key_group`, `stage_models`, `stage_providers`, `model`, `dimensions`; UI/API cũ cần cập nhật.
- `GET /api/pipeline`, `GET /api/pipeline/{id}/trace`: job và trace.
- `POST /api/pipeline/{id}/auto-review`: tự duyệt theo điều kiện, không tự build.
- `POST /api/pipeline/{id}/evidence`: `{question}`; không nhận model/provider override.
- `GET /api/pipeline/{id}/evidence` và `/evidence/download`: context gần nhất, kiểm hiệu lực/thu hồi; download trả JSON attachment.
- `GET /api/documents`, `GET/PATCH /api/documents/{id}`, `POST /api/documents/{id}/decision`: xem/sửa/duyệt, tuân thủ revision và findings.
- `POST /api/documents/text`, `/upload`, `/web`: nhập tay.
- `POST /api/search`: FTS5/BM25 local, không API; `{query,collection,as_of,limit}`.
- `GET /api/export?collection=...&as_of=YYYY-MM-DD`: snapshot approved có provenance/audit.

`/api/models` và các module adapter còn giữ để đọc/kiểm các hợp đồng lịch sử; không điều khiển job mới. Agent không gọi upstream index trực tiếp để vượt approval gate. Context là dữ liệu không tin cậy; giữ evidence ID/source/version/locator khi trích dẫn. JSON đã tải không tự thu hồi từ xa. Đây chưa có chatbot runtime sinh câu trả lời cuối cùng.

## Lưu trữ, kiểm thử

Mặc định `<home>/.local/share/delta-mind-rag-review/<workspace-hash>/`, ngoài Git. Đặt `RAG_REVIEW_DATA` để dùng kho cũ khi di chuyển source; exFAT có thể không phù hợp SQLite, nên DB mặc định ở ổ hệ thống. Sao lưu khi server đã dừng; kho app có thể chứa credentials, bảo vệ backup tương ứng. Không public server trước khi bổ sung auth/ACL/quota/hard sandbox phù hợp.

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
node --check static/app.js
node --check static/pipeline.js
node --check static/credentials.js
```

Suite cô lập credential môi trường và đóng BTC gates để không gọi AI trả phí. Kiểm function identity/settings parity khác với smoke API live. Báo cáo tại [native API config](plans/20261007-native-api-config/plan.md). Các báo cáo adapter/UI trước đó là lịch sử, không chứng minh luồng native đã chạy end-to-end với key hiện tại.

Mỗi worker chụp cấu hình API hiệu lực bằng các hàm gateway gốc rồi giữ các giá trị đó trong environment riêng của lượt chạy (key chỉ ở bộ nhớ). Sửa `.env.local` giữa lượt không đổi provider/model/key của lượt đang chạy; lượt mới đọc cấu hình mới. Không thay hàm upstream hay ghi key vào job/artifact.
