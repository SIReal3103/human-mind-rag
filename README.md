# Human Mind RAG

Bản hợp nhất engine và UI từ [scope-data-bot](https://github.com/Qyroven/scope-data-bot), kèm các bản sửa đã kiểm thử qua luồng crawl và duyệt nguồn Hà Nam. Repo này chứa đầy đủ mã để chạy, không cần clone engine phụ. Xem [nguồn gốc mã](NOTICE.md).

Bot CLI nhận **scope dữ liệu**, tự tìm nguồn → crawl → parse/check → save → chunk → embedding → index → gói evidence cho LLM. Ingestion không cần câu hỏi của user và không sinh câu trả lời.

Scope có thể là tài liệu khái niệm (định lý, giáo trình, nguyên lý vaccine) hoặc số liệu thống kê. Pipeline giữ raw source, metadata, locator và trace. Generic evidence luôn mang trạng thái review; việc index thành công không xác nhận số liệu đúng hoặc phạm vi đã đủ.

Truy vấn tìm nguồn được tạo theo loại scope: scope có mốc năm/số liệu ưu tiên nguồn thống kê, scope khái niệm ưu tiên giải thích/giáo trình. Nếu search bị CAPTCHA hoặc không thể trả kết quả, lượt chạy báo `incomplete` và ghi nguyên nhân trong `discovery.json`; không tự coi 0 nguồn là kết quả hợp lệ. Muốn crawl tự động cần search provider hoạt động và cấu hình model/key hợp lệ.

## Một repo, giao diện Human in the Loop

```bash
./run-ui.sh
# Mở http://127.0.0.1:8765
```

Launcher cài runtime UI đã khóa một lần; không clone repo khác. Cấu hình key trong Settings → tạo phiên và nhập scope → crawl/parse/check → đối chiếu bản gốc và duyệt → tạo index → lấy evidence cho chatbot. Tự duyệt mặc định tắt. Ưu tiên Docling nếu đã cài local; chạy `./setup-parser.sh` để cài OCR/layout, hoặc `DOCUMENT_PARSER=native ./run-ui.sh` để dùng parser nhẹ. CLI bên dưới vẫn dùng được riêng và không có bước duyệt UI.

Tài liệu đầy đủ: [UI và API](review_ui/README.md). Bản duyệt giữ bảng/provenance; sửa text bỏ tọa độ cũ. Bản trích xuất thiếu có thể thay bằng text đầy đủ đã đối chiếu toàn bộ nguồn; cần người duyệt xác nhận cảnh báo, bản gốc và lịch sử parser vẫn được giữ. UI chỉ báo index sẵn sàng khi có `ready_partial` và ít nhất một chunk; build rỗng/`no_evidence` báo lỗi. Cache embedding dùng chung trong kho UI. Thu hồi/hết hiệu lực chặn index cũ; sang ngày mới không bắt rebuild nếu tập phiên bản còn hiệu lực không đổi. UI phát triển từ [Human Mind](https://github.com/SIReal3103/human-mind-rag); xem [nguồn gốc](NOTICE.md).

## Chạy

Python 3.12 hoặc 3.14. SQLite phải có FTS5.

```bash
git clone https://github.com/SIReal3103/human-mind-rag.git
cd human-mind-rag
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
cp .env.example .env.local
# Điền key trong .env.local; không commit file này.
./setup-parser.sh  # Cần uv; tải model Docling/OCR local một lần, runtime Python 3.12 riêng.
./run-data.sh --scope 'Thu thập tài liệu về định lý Pythagoras, điều kiện áp dụng và ví dụ'
```

Các lựa chọn input: `--scope`, `--brief-file <file.txt>` hoặc `--from-run bot-runs/<id>` để tiếp tục một lượt crawl đã có. Không tự crawl lại khi dùng from-run.

`--parser docling --ocr auto` dùng Docling, giữ text PDF có sẵn và OCR vùng ảnh. `--ocr full` OCR toàn trang; `--ocr off` tắt OCR. `--document-max-pages 40` giới hạn số trang đầu, luôn báo partial nếu tài liệu dài hơn. Các flag parse chỉ áp dụng cho lượt scope mới; `--from-run` không parse lại bản gốc.

`setup-parser.sh` cài dependency đã pin trong `.venv-docling`, tải layout/table/EasyOCR tiếng Việt/Anh. Không cần key AI cho parse, tài liệu được xử lý local. Máy khác cần chạy setup một lần; có thể dùng lại cùng model embedding nếu provider hỗ trợ. Model parse không phụ thuộc gateway BTC/OpenAI.

Giới hạn mặc định: 5 nguồn, 12 URL, depth 1, 400 chunks. Thay bằng `--max-sources`, `--max-pages`, `--max-depth`, `--max-chunks`. Chạy nhỏ trước; search/model/embedding dùng API trả phí. Mỗi request có timeout và giới hạn response, nhưng chưa có giới hạn tổng chi phí bằng tiền hoặc cancel service.

## Provider

`AI_PROVIDER=openai`: key OpenAI riêng, gpt-4.1-mini cho planner/search/check/rerank, text-embedding-3-small 1536 chiều mặc định. Đây là profile đã dùng để test live. Biến môi trường ưu tiên hơn .env.local.

`AI_PROVIDER=btc`: BTC_API_KEY, gpt-6-luna, text-multilingual-embedding-002 và EMBEDDING_DIMENSIONS=768. Request chỉ tới api.thucchien.ai, không tự fallback sang OpenAI. Phải smoke-test đúng model/endpoint/protocol rồi mới bật từng BTC_*_VERIFIED; bản hiện tại chưa chạy bằng key BTC và để các gate đóng. Đổi provider/model/dim cần xây index phù hợp; không so vector khác profile. Gemini-embedding-2 luôn một input/request.

Các endpoint/model BTC được đối chiếu với [Embedding BTC](https://docs.thucchien.ai/docs/round-2/user-guide/embeddings) và [Web search BTC](https://docs.thucchien.ai/docs/round-2/user-guide/google-search-grounding). Payload structured output qua BTC cần kiểm riêng; tên SDK/model không chứng minh gateway hỗ trợ toàn bộ protocol.

## Output

Mỗi lượt nằm ở `bot-runs/<id>/`:

| File/thư mục | Nội dung |
| --- | --- |
| scope.json, report.json, report.html | Scope, nguồn tìm được, lỗi và phần thiếu |
| raw/, parsed/ | Snapshot nguồn, parser output và bảng có vị trí ô |
| parsed/* với parser Docling | Native Docling JSON, trang/bbox, grid ô gộp, config/version, cảnh báo OCR/bảng và cờ partial |
| lineage.json, feedback.json | Truy ngược, lỗi phát hiện và đề xuất xử lý |
| data/chunks.json | Text, source ID/version, URL, locator, token count, quality, trace ID |
| data/index.sqlite | Vector + FTS5/BM25, model và dimensions |
| data/embedding-receipts.json | Response hash, usage và cache hits |
| data/manifest.json | Trạng thái index và thiếu định nghĩa/phạm vi |
| data/llm-input.json | Gói evidence theo scope trong 6000 tokens, báo đoạn bị bỏ vì budget |
| data/artifacts/ | Bản bất biến để rebuild không phá trace cũ |

`ready_partial` = có index dùng được, chưa chứng minh đầy đủ/chính xác. `no_evidence` = không có đoạn đủ điều kiện. `failed` = không được phục vụ index. Exit 0 khi có evidence; 2 khi thiếu evidence/lỗi. Documents out-of-scope/unassessed bị loại, review giữ cờ review. Cache theo provider/scope/text hash/model/dim/chunker.

## Phía LLM gọi khi user hỏi

```python
from data_pipeline import retrieve

context = retrieve("bot-runs/<id>", user_question, budget=6000, top_k=6)
# Chatbot truyền context vào LLM và yêu cầu trích evidence ID/source.
```

Luồng query: kiểm phạm vi câu hỏi → query embedding → cosine + BM25 → RRF → LLM relevance scoring → thêm đoạn liền kề → context có nguồn và cờ chất lượng. Đây chưa phải dedicated cross-encoder reranker. `rerank=False` bỏ gate/rerank; chế độ này không bảo đảm abstention, chỉ là truy hồi candidates.

Không nhét toàn bộ corpus vào prompt. Context bị giới hạn, metadata và đoạn omitted được báo rõ. Mỗi context lưu riêng `data/context-*.json` với trace ID. Scope chỉ là phạm vi corpus; câu hỏi do chatbot nhận sau ingestion.

Embedding cache dùng lại vector khi provider/model/số chiều và văn bản đầu vào giống nhau, kể cả giữa các scope; mỗi run vẫn giữ assessment và nguồn riêng. Các chunk trùng đầu vào trong một run chỉ gửi embedding một lần. `embedding-receipts.json` ghi `cache_hits` và `deduplicated_chunks`. Cache cũ theo scope được chuyển sang khóa mới khi đọc, không cần gọi API lại.

## Kiểm và truy ngược

```bash
.venv/bin/python -m unittest discover -p 'test_*.py'
.venv/bin/python -m pip check
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python audit_run.py --run bot-runs/<id>
.venv/bin/python trace.py --run bot-runs/<id> --target n00001
```

`audit_run.py` đối chiếu text spans, vị trí hàng/ô, chunks/index, dimensions, token count và hash trên trace. Nó không xác nhận sự thật trong tài liệu hoặc độ trung thực với PDF/HTML đã render. Nơi phát hiện lỗi không tự chứng minh nguyên nhân gốc; feedback chưa tự sửa sự thật.

## Giới hạn hiện tại

Parser nhẹ cho HTML/CSV/JSON; Docling local cho PDF, PNG/JPEG/TIFF/WebP một frame và DOCX/PPTX/XLSX. HTML giữ article lead có thể bị readability bỏ sót và chuyển MathML thông dụng thành text tìm kiếm; `html_leads`/`html_math` giữ XPath cùng MathML gốc để đối chiếu. Khi trích xuất precision bỏ sót phần lớn nội dung, parser thử khôi phục đoạn văn từ vùng article/body có đánh dấu, loại các khối điều hướng, footer và nội dung liên quan; HTML gốc vẫn được giữ để đối chiếu. OCR EasyOCR vi/en, bảng TableFormer, CPU mặc định 2 threads. Docling mặc định xử lý 40 trang đầu, timeout cứng 180 giây, tối đa input 10 MB/500 trang PDF, output 600k ký tự/20 MB JSON; file Office có giới hạn giải nén, ảnh tối đa 20 MP. Timeout kết thúc cả nhóm tiến trình. Chưa có hard memory sandbox; không dùng trực tiếp cho upload không tin cậy từ nhiều tenant.

`.env.example` yêu cầu Docling. `DOCUMENT_PARSER=auto` dùng Docling khi runtime đã cài; nếu chưa có thì PDF dùng pypdf và ghi hạn chế rõ, ảnh/Office báo cần setup. `--parser native` chọn pypdf. Native long PDF vẫn giữ tối đa 24 trang theo scope (scan tối đa 500 trang/45 giây). Cache parse local theo raw/config/worker/dependency-lock, không cache assessment; không bị lẫn scope. Cache không phải kho bằng chứng: từng run vẫn giữ raw/parsed và trace riêng.

OCR có thể mất chữ hoặc đọc sai ô bảng; cần kiểm lại nguồn trước khi dùng số liệu. Cờ chất lượng và giá trị null không bảo đảm đã phát hiện mọi lỗi. Formula enrichment ngoài MathML, mô tả ảnh/biểu đồ và chữ viết tay chưa được kiểm chứng; chưa bật các model enrichment nặng. Không có cam kết đọc đúng mọi công thức/bảng, hay mọi ngôn ngữ. Nguồn chặn/JavaScript/định dạng không hỗ trợ giữ lỗi. Tham khảo API sử dụng tại [Docling OCR](https://docling-project.github.io/docling/_generated/examples/full_page_ocr/) và [offline/local models](https://docling-project.github.io/docling/usage/advanced_options/).

Một writer cho mỗi run; operation đồng thời báo RUN_BUSY. Crash có thể để .data-lock, cần kiểm run trước khi xóa lock cũ. Exact vector search phù hợp corpus nhỏ. UI hiện phục vụ một nhóm nhỏ tại local; chưa có tenant ACL hoặc egress sandbox cho dịch vụ crawl công khai. Chỉ nhận nguồn công khai; không đưa tài liệu cá nhân vào repo.

Repo không chứa key, raw pages, vectors, private guide hay thư mục các lượt chạy. Public giữ code, hướng dẫn sử dụng, test hồi quy và CI. Báo cáo thử nghiệm, review và script chạy benchmark live giữ local trong `local-evidence/` (không được Git theo dõi). `benchmarks/vietnam-population-2020-2024.json` là dữ liệu đối chiếu mà connector World Bank sử dụng khi chạy; cần giữ cùng code. GitHub CI kiểm offline trên Python 3.12/3.14, không gọi inference bằng key thật.
