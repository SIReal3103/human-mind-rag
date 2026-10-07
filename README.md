# Human Mind — Duyệt tài liệu RAG

Trang quản trị local cho luồng **nhập nguồn → kiểm sơ bộ → người duyệt → kho tri thức**. FastAPI + SQLite FTS5 + giao diện web tiếng Việt. Tích hợp parser và chunker thật từ [scope-data-bot](https://github.com/Qyroven/scope-data-bot) tại commit `cb37446a00c6283cbb596df524885cfcb08a9fe7`.

Hướng dẫn bàn giao: [Agent guide — thao tác và đối chiếu upstream](AGENT-GUIDE.md).

## Chạy

Yêu cầu Python 3.12, Git, SQLite có FTS5 và mạng khi cài dependencies/tokenizer lần đầu.

```bash
git clone https://github.com/SIReal3103/human-mind-rag.git
cd human-mind-rag
bash setup.sh
bash run.sh
```

Mở **http://127.0.0.1:8765**. `setup.sh` clone upstream riêng vào `.runtime/scope-data-bot`, khóa đúng commit và cài runtime `.venv`. Không chép code upstream vào Git của đội; upstream hiện chưa khai báo license. Không thay commit của clone đã có. Xem [báo cáo đánh giá](plans/20261007-rag-document-review/reports/scope-data-bot-review.md).

Nếu đã có clone upstream đúng commit và runtime riêng:

```bash
SCOPE_BOT_PATH='/path/to/scope-data-bot' \
RAG_REVIEW_PYTHON='/path/to/venv/bin/python' \
bash run.sh
```

Có thể đặt `RAG_REVIEW_PORT`, `RAG_REVIEW_DATA`, `RAG_REVIEW_VENV`, `RAG_REVIEW_PYTHON` và `SCOPE_BOT_PATH`. Nhập/duyệt và tìm từ khóa local không cần key; pipeline AI cần key của provider được chọn. Không tự đọc `.env` của repo đội hoặc lấy key từ `.env.local` upstream. Worker parse/chunk local không nhận key; worker pipeline nhận đúng key đã chọn qua stdin. Tokenizer có thể tải vocabulary công khai một lần. `SSL_CERT_FILE` trỏ tới certifi để Python xác minh HTTPS bằng CA có sẵn; không thay opener upstream.

## Dùng trang

### Cấu hình API key

Mở **Cấu hình API key** trên thanh điều hướng hoặc `http://localhost:8765/#settings`:

- **Gateway BTC:** ô `BTC_API_KEY` riêng cho `api.thucchien.ai`.
- **Nhà cung cấp riêng:** OpenAI, Google (Gemini/Veo), Anthropic và DeepSeek, mỗi dịch vụ có key độc lập. Key Google không tự chứng minh tài khoản có quyền dùng Veo.
- Nút **Lưu/Thay và kiểm tra key** lưu rồi gọi kiểm tra xác thực; chỉ hiện trạng thái, không trả lại key hoặc vài ký tự cuối. Gỡ key cần đánh dấu xác nhận trong trang.
- **Reset tất cả key** → **Xác nhận xóa tất cả key** xóa toàn bộ key đã lưu trong ứng dụng (kể cả BTC), rồi đưa con trỏ về ô BTC. Hủy giữ nguyên key. Reset không xóa tài liệu RAG, file key gốc hoặc thu hồi key tại nhà cung cấp.
- Key lưu trong `<thư mục dữ liệu>/credentials/providers.json`, quyền file `0600`, thư mục `0700`, ngoài source/Git và DB tài liệu. File là plaintext được giới hạn quyền hệ điều hành, **chưa có mã hóa riêng/Keychain**. Bản sao lưu toàn thư mục dữ liệu sẽ bao gồm key; cần bảo vệ bản sao lưu tương ứng.
- Không lưu key vào sessionStorage/localStorage, audit tài liệu, source/chunks, export hoặc API response. Các lỗi validation không phản hồi lại input chứa key.
- API PUT chỉ lưu key; nút Lưu/Thay trên giao diện gọi thêm kiểm tra liệt kê model, không sinh nội dung và không tự fallback. Worker parse/chunk vẫn không nhận key. Có thể bấm **Kiểm tra key** lại khi cần. Thành công chỉ xác nhận lời gọi đó, chưa chứng minh billing hay quyền dùng mọi model/tìm web/embedding/Veo.

API local: `GET /api/credentials` chỉ trả metadata; `PUT /api/credentials/{btc|openai|google|anthropic|deepseek}` nhận `{"api_key":"..."}`; `DELETE` gỡ key; `POST /api/credentials/reset` với `{"confirm":true}` xóa tất cả key đã lưu. Mutation yêu cầu token phiên/origin như API khác. `run.sh` vẫn chạy một worker local; chưa hỗ trợ chia sẻ kho key giữa nhiều process/tenant.

### Nhập và duyệt tài liệu

1. Thêm tệp PDF/TXT/MD/HTML (UTF-8 cho text), dán văn bản hoặc nhập URL HTTP(S) công khai. Tối đa 10 MB; nội dung sau parse tối đa 600.000 ký tự.
2. Chọn bộ tài liệu, mã nguồn ổn định và phiên bản. Ngày upload **không** được dùng làm ngày hiệu lực. Bật “phụ thuộc thời gian” để bắt buộc ngày bắt đầu; ngày kết thúc là mốc không bao gồm.
3. Đối chiếu **Nguồn gốc**, nội dung trích xuất, từng đoạn, lỗi/cảnh báo. Sửa text/metadata ở trạng thái chờ; bản gốc vẫn giữ nguyên. Khi sửa text, locator trang cũ bị bỏ để không tạo citation giả.
4. Nhập người duyệt, ghi chú và xác nhận đã kiểm các cảnh báo. Lỗi chặn không thể bỏ qua. Phê duyệt ghi trạng thái và chỉ mục trong một transaction.
5. Thử **Tra cứu nguồn** trên đúng bộ tài liệu/ngày áp dụng hoặc **Xuất kho JSON**. Từ chối/thu hồi không được truy hồi hay export.

Từ chối cần lý do; có thể mở lại bản bị từ chối. Bản đã duyệt bất biến: nhập phiên bản mới để thay nội dung. Nếu cùng nguồn có hiệu lực chồng, thu hồi bản cũ rồi duyệt bản mới, hoặc nhập các khoảng không chồng. Chưa có thao tác thay thế hai bản nguyên tử; thu hồi trước có thể tạo khoảng trống ngắn. Không xóa lịch sử cũ.

Mỗi quyết định có revision, tên người duyệt, thời gian server, hash nguồn/nội dung và ghi chú. Duyệt revision cũ hoặc bấm lặp không tạo publish trùng. Tên người duyệt là nhãn audit của phiên local, **chưa phải danh tính được hệ thống đăng nhập xác thực**.

## Crawl → người duyệt → semantic RAG

Mở **Crawl & RAG pipeline**. Checkout [scope-data-bot](https://github.com/Qyroven/scope-data-bot) giữ nguyên commit `cb37446a00c6283cbb596df524885cfcb08a9fe7`; app từ chối checkout có thay đổi tracked. Human Mind bổ sung adapter model riêng, không sửa source upstream.

1. **＋ Tạo phiên mới**: nhập phạm vi và tên bộ tài liệu, không cần URL. Mặc định 12 trang, sâu 1, tối đa 5 nguồn đầu. Đây là giới hạn crawl, không phải số lời gọi AI.
2. Chọn **Bộ key dùng cho toàn bộ phiên**: **BTC** dùng duy nhất `BTC_API_KEY` cho mọi model; **Ngoài** dùng key riêng theo họ model (OpenAI, Google/Gemini, DeepSeek). Chọn model cho lập kế hoạch, tìm nguồn, kiểm nội dung/xếp nguồn, embedding và kiểm phạm vi/rerank evidence. Không tự fallback.
3. **Bắt đầu crawl** gọi AI lập kế hoạch, tự tìm URL, rồi crawler/parser/check upstream. Cụm “đến nay/hiện tại” được quy đổi một lần sang năm hiện tại theo giờ Việt Nam, lưu tại `effective_scope`, hiển thị trong phiên. Planner bị ràng buộc giữ đúng năm; không bỏ validator upstream để chấp nhận sai phạm vi.
4. **Tiếp tục duyệt N tài liệu →** lọc đúng phiên. Đối chiếu bản gốc, sửa nếu cần, ghi người duyệt và phê duyệt/từ chối. Tài liệu crawl được nhập vào pending; nếu bật tự duyệt, chỉ bản đạt toàn bộ chính sách auto-review-v1 mới được approve tự động (xem bên dưới). Điểm trích xuất không phải xác suất đúng.
5. **Tạo index từ bản đã duyệt** xuất snapshot approved còn hiệu lực, giữ audit/revision/hash/provenance, gọi `data_pipeline.build` với adapter embedding. Chỉ model embedding được chọn ở bước này. Model Gemini embedding 2 gửi từng đoạn một request; app và upstream cùng kiểm số lượng/chiều/vector. Tối đa 400 chunks.
6. **Lấy evidence** gọi `data_pipeline.retrieve`: kiểm phạm vi bằng model, embedding câu hỏi, tìm kiếm và rerank. Model evidence được chọn lại trong cùng bộ key; query embedding luôn khóa theo provider/model/chiều của index. Đọc trích đoạn và nguồn rồi tải JSON cho agent. Đây là căn cứ để LLM trả lời, chưa phải câu trả lời.

Catalog lấy các model liên quan đến RAG từ [bảng giá BTC](https://docs.thucchien.ai/docs/round-2/user-guide/pricing), [tìm web](https://docs.thucchien.ai/docs/round-2/user-guide/google-search-grounding) và [embedding](https://docs.thucchien.ai/docs/round-2/user-guide/embeddings). DeepSeek không xuất hiện ở tìm web; model ảnh/video/âm thanh không xuất hiện trong luồng này. `text-multilingual-embedding-002` và `text-embedding-005` chỉ có ở BTC, vì key Google AI Studio không phải credential Vertex. `gpt-4.1-mini` được giữ cho bên Ngoài để tương thích phiên trước. Có tên trong catalog không đảm bảo key đã được cấp quyền model.

### Tích hợp và giới hạn

`api_routing.py` bọc gateway calls trong worker riêng; `model_gateway.py` gọi endpoint phù hợp và giữ raw response/receipt thực. OpenAI dùng Responses; Gemini trực tiếp dùng generateContent/Google grounding/embedContent; Gemini qua BTC dùng Chat Completions với googleSearch; DeepSeek dùng JSON mode và vẫn qua validator upstream. Khôi phục tham chiếu hàm sau worker; metadata provider của index phản ánh đúng Google/BTC/OpenAI. Link trích dẫn trung gian Google được giải bằng HEAD tại đúng host Google; ghi ánh xạ citation → URL đích trong receipt. Không tải nội dung nguồn ở bước này; crawler gốc vẫn kiểm robots/TLS của URL đích. Không sửa discovery, crawler, parser, semantic validators, thuật toán retrieval hoặc bước duyệt.

Luồng mới `upstream-model-routing` dùng các API theo tài liệu và báo kết quả từng lời gọi; không dùng cờ legacy `BTC_*_VERIFIED` để thay cho kiểm chứng thực tế. API legacy với `provider`/`stage_providers` vẫn giữ gateway/capability gates gốc. BTC chưa có key tại lần kiểm chứng này, nên chưa khẳng định live BTC thành công. Không tự đặt cờ capability hoặc chuyển sang key ngoài.

Nguồn web có thể lỗi TLS, robots, HTTP, CAPTCHA hoặc không có nội dung phù hợp. Các lỗi nguồn không đồng nghĩa key hỏng. Không vô hiệu hóa TLS hoặc vượt trang chặn. Khi một nguồn lỗi, crawler gốc tiếp tục các nguồn khác trong giới hạn phiên. Tài liệu nhận được vẫn cần duyệt; hoàn tất phiên không đồng nghĩa đã thu đủ tài liệu.

### Key, lỗi và trace

Cấu hình key có trạng thái hiện tại, ngày lưu/ngày kiểm tra và nút kiểm tra. Thay key xóa kết quả sức khỏe cũ; kết quả đang chạy được gắn phiên bản key nên không ghi đè trạng thái key mới. **Lịch sử phiên cũ không chạy lại khi thay key**. Muốn thử lại, mở cấu hình phiên rồi bấm Bắt đầu crawl để tạo lượt mới.

- HTTP 401 / `invalid_key`: xác thực bị từ chối.
- 403: thiếu quyền; 402/quota: hạn mức/billing; 429: giới hạn lượt gọi/quota.
- `invalid_output`, `PLANNER_YEAR_MISMATCH`: đầu ra model không đạt hợp đồng, không phải kết luận key hỏng.
- `model_unavailable`, `invalid_request`, `network_error`: lỗi model, yêu cầu hoặc mạng được phân biệt.

Trace ghi bước, model, provider và tên key, không có giá trị key hay raw body lỗi nhà cung cấp. Key đã thay/gỡ có nhãn phiên cũ. HTTP GET liệt kê model chỉ chứng minh quyền gọi endpoint đó, không đảm bảo mọi model/tìm kiếm/embedding/Veo hoạt động. Model calls thực tế được ghi riêng.

### API local

- `GET /api/models`: catalog, chức năng model, bộ key, defaults, nguồn tài liệu và ngày hiện tại.
- `POST /api/pipeline`: `{action:"crawl"|"build",scope,collection,key_group:"btc"|"external",stage_models:{planner,search,check,embedding,evidence}}`. Crawl nhận `max_sources,max_pages,max_depth`. Chỉ cần các key của bước sẽ chạy. Job mới lưu `effective_scope`, `scope_resolved_on`, model/provider từng bước và phiên bản credential, không lưu giá trị key.
- `GET /api/pipeline`: danh sách phiên; `GET /api/pipeline/{id}/trace`: lineage và API calls.
- `POST /api/pipeline/{id}/evidence`: `{question,model?}` chỉ thay model scope gate/rerank trong bộ key của index; không thay embedding. Phiên legacy vẫn nhận `provider?` theo hợp đồng cũ. Giao diện không gán model mới cho index legacy.
- `GET /api/pipeline/{id}/evidence`: kết quả lần tra trước; không gọi AI, vẫn kiểm thu hồi/hiệu lực.
- `POST /api/credentials/{provider}/check`: kiểm xác thực, cần CSRF, trả kết quả an toàn và metadata; không trả key.

Mutation cần token phiên/origin. Dữ liệu tại `<data>/pipeline/<id>/`. Một crawl/build chạy tại một thời điểm; job có PID chủ đã chết được đánh dấu interrupted khi khởi tạo lại. Job còn chủ sống hoặc legacy không có PID không bị kết luận đã dừng. Sửa/thu hồi tài liệu, đổi tập đã duyệt hoặc sang ngày mới chặn index cũ. Bot phải gọi endpoint evidence để áp dụng gate; JSON đã xuất không tự thu hồi từ xa.

Trang giữ lịch sử riêng, chỉ mở một phiên. Tạo phiên mới dọn phạm vi/bộ tài liệu, giữ bộ key/model đang chọn và tắt tự duyệt; lần dùng đầu mặc định BTC/12 trang/sâu 1. Không xóa tài liệu hoặc key. Nhập URL trong **Thêm tài liệu** là chức năng riêng, không phải nguồn seed của pipeline.

### Kiểm chứng hiện tại

Ngày 2026-10-07: key OpenAI mới khớp file người dùng và trả HTTP 200; Google trả 200. Lỗi phiên `3e80f42f...` xảy ra sau khi planner gọi thành công vì “2016 đến nay” bị hai bộ lập kế hoạch hiểu khác nhau. Không còn coi đây là lỗi key.

Đã chạy thật JSON/Google grounding/Gemini embedding 2; tạo index 4 chunks từ một tài liệu đã được duyệt trước đó trong `binh-phuoc-demo`, truy hồi được 4 đoạn evidence, provider manifest là Google. Không tự phê duyệt tài liệu crawl mới. Báo cáo đầy đủ tại [model selection validation](plans/20261007-model-selection/reports/validation.md). Các [báo cáo cũ](plans/20261007-stage-api-and-key-health/reports/validation.md) mô tả key và phiên ở thời điểm cũ, không phải sức khỏe key hiện tại.

**Tra cứu từ khóa không dùng key** vẫn dùng FTS5 trên bản approved; không phải semantic retrieval.

## Kiểm sơ bộ và mức tự tin

Điểm **Chất lượng trích xuất** là chỉ số quy tắc 0–100, chưa hiệu chỉnh. `quality.method=extraction-rules-v1`; mỗi finding có severity, mô tả, snippet/vị trí khi có và điểm trừ. Các kiểm hiện có: rỗng, parse một phần, cảnh báo parser, văn bản quá ngắn, ký tự lỗi, chỉ dẫn có dạng prompt injection, dấu hiệu bí mật, nguồn trùng và thiếu hiệu lực bắt buộc.

`factual_confidence=unverified`: không khẳng định phát hiện hết sai sót hay xác minh sự thật. Người duyệt phải kiểm nội dung chuyên môn, nguồn có thẩm quyền và các mâu thuẫn. Không có LLM judge đang chạy, không dùng số 85/100 như “85% đúng”. Phê duyệt không biến điểm này thành xác suất đúng.

PDF có text dùng parser native của upstream; giữ trang thật. PDF không đọc được vẫn nằm ở staging với bản gốc và lỗi chặn. Có thể nhập text đã đối chiếu thủ công hoặc dùng OCR local. Chế độ Docling là tùy chọn:

PDF trộn chữ/scan: trang có ảnh nhưng không có text khiến toàn bản bị đánh dấu partial và chặn duyệt; trang trắng không có ảnh không bị coi là thiếu nội dung. Với bản partial, chạy OCR/nhập lại bản đầy đủ hoặc nhập nguồn text hoàn chỉnh đã đối chiếu. Kiểm này không nhận ra mọi hình/bảng bị bỏ sót trên trang vẫn có chữ.

```bash
cd /path/to/scope-data-bot
bash setup-parser.sh
# Sau khi cài runtime/model local thành công:
DOCUMENT_PARSER=docling SCOPE_BOT_PATH=/path/to/scope-data-bot bash /path/to/rag-review/run.sh
```

Docling tải model một lần; runtime OCR của ứng dụng này chưa được nghiệm thu. Không coi native PDF là OCR cho scan, hoặc cam kết bảng/công thức được đọc đúng. Parser/chunker chạy subprocess có timeout; chưa có sandbox RAM cứng.

## Nối với agent bot

Repo đội chưa có bot runtime để sửa trực tiếp. Endpoint `/api/search` là phần retrieval đã hoạt động, trả evidence từ nguồn đã duyệt. Đây là **tìm từ khóa FTS5/BM25**, chưa có semantic embeddings hay rerank. Có lọc collection, trạng thái và khoảng hiệu lực trước LIMIT. Điểm rank không phải confidence.

Ví dụ gọi từ backend agent chạy cùng máy (thư viện chuẩn Python):

```python
import json
from urllib.request import Request, urlopen

base = "http://127.0.0.1:8765"
with urlopen(base + "/api/config", timeout=10) as response:
    token = json.load(response)["csrf_token"]
payload = {"query": question, "collection": "general", "as_of": "2026-10-07", "limit": 6}
request = Request(
    base + "/api/search",
    data=json.dumps(payload).encode(),
    headers={
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
    },
)
with urlopen(request, timeout=15) as response:
    context = json.load(response)
if context["status"] == "no_evidence":
    # Bot báo thiếu căn cứ; không tự tạo tài liệu hay câu trả lời chắc chắn.
    ...
else:
    evidence = context["results"]
    # Cấp evidence như dữ liệu, yêu cầu trích source_id/document_version/chunk_id/locator.
```

`GET /api/export?collection=general&as_of=2026-10-07` trả snapshot JSON `delta-mind-approved-rag-v1`, gồm phiên bản, SHA-256, provenance, chunks và audit. Snapshot đã export không tự cập nhật khi nguồn bị thu hồi; bot nên gọi API mỗi lần hoặc đồng bộ lifecycle trước khi dùng snapshot. `collection` là phân vùng nội dung của local operator, chưa phải ACL nhiều tenant.

Semantic RAG được nối qua mục **Crawl & RAG pipeline** bên dưới. Kiểm ngữ nghĩa dùng model theo upstream khi chạy crawl; tự duyệt chỉ khi bật chính sách riêng, không fallback provider.

## Lưu trữ và giới hạn vận hành

- Dữ liệu mặc định: `~/.local/share/delta-mind-rag-review/<12 ký tự SHA-256 của đường dẫn module>/`; `review.sqlite` và `originals/`. Dữ liệu nằm ngoài Git. Đặt `RAG_REVIEW_DATA` để chọn thư mục khác trên filesystem hỗ trợ SQLite.
- Máy thực tế dùng ổ exFAT cho repo: đã tái hiện `SQLITE_READONLY_DBMOVED` khi tạo FTS. Vì vậy database mặc định đặt trên ổ hệ thống. Di chuyển code làm đổi workspace ID; giữ `RAG_REVIEW_DATA` cũ nếu muốn dùng lại kho.
- Sao lưu toàn bộ thư mục dữ liệu khi server đã dừng. Không tự xóa tài liệu khi khởi động/restart.
- Server chỉ bind loopback; kiểm Host/Origin/token cho mutation. Không public deployment, đăng nhập, vai trò độc lập, nhiều reviewer/tenant, quota tổng hay queue bền. Không đổi bind thành public trước khi có các phần đó.
- Nhập URL thủ công chặn IP không public, credentials/port lạ, recheck redirect và pin địa chỉ DNS; có timeout và giới hạn byte. Không chạy JavaScript của trang, không đăng nhập/crawl cả website. HTML gốc được hiển thị như text, không thực thi.
- Không sửa checkout upstream. Adapter gọi crawl trong worker riêng, rồi build/retrieve upstream trên snapshot đã duyệt riêng biệt. Không build trực tiếp thư mục crawl.
- Bản đang sửa được giữ trong sessionStorage của tab để tránh mất khi reload; khôi phục chỉ khi revision còn khớp. Lưu hoặc chọn bỏ thay đổi sẽ xóa bản nháp này.

## Kiểm thử

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
node --check static/app.js
```

Tests dùng thư mục tạm, parser/chunker upstream thật. Xem [upstream validation](plans/20261007-rag-document-review/reports/upstream-validation.md) và [kiểm chứng ứng dụng](plans/20261007-rag-document-review/reports/app-validation.md). Các fixture được tạo riêng trong test; giao diện không seed tài liệu giả.

### Sửa kết quả kiểm tra bằng chứng

Với luồng chọn model từng bước, nếu model chọn ID không tồn tại hoặc năm không có trong đoạn đã chọn, lớp tích hợp yêu cầu cùng model sửa đúng một lần. Cả hai phản hồi và kết quả kiểm tra được giữ trong trace; không sửa/xóa năm trong phản hồi để làm cho nó đạt. Nếu lần sửa vẫn sai, bộ kiểm tra từ chối đánh giá AI và bản tải được chuyển sang hàng chờ duyệt. Không tự retry lỗi xác thực, không đổi model/provider và không vượt robots/TLS. Lượt sửa có thể phát sinh thêm một lời gọi AI cho mỗi tài liệu.

Tài liệu đã trích được nhưng bị AI đánh giá `out_of_scope` vẫn vào hàng chờ, có cảnh báo và lý do; người duyệt quyết định thay vì mất tài liệu trước khi xem. Không tự phê duyệt hoặc index các bản này. Nhập lại cùng artifact trong một phiên không tạo bản trùng.

### Tự động duyệt và tiếp tục qua UI

Mặc định vẫn duyệt thủ công. Bật **Tự động duyệt tài liệu đủ điều kiện** trước khi crawl hoặc bấm nút cùng tên trong kết quả phiên để áp dụng `auto-review-v1`: bản mới revision 1, đang pending, có đoạn văn, điểm trích xuất >=90, không warning/error, nguồn web, assessment gốc khớp scope và có evidence, không partial/truncated. Tài liệu không đạt vẫn pending, có lý do; không tự bỏ cảnh báo hoặc ép approve. Auto-approval là quy tắc vận hành, không phải xác minh sự thật hay quyết định của người duyệt. Audit, search và snapshot/index phân biệt automatic/manual; có thể thu hồi như bản duyệt tay.

Có ít nhất một bản approved là có thể chuyển sang tạo index, dù còn bản pending. UI không tự gọi embedding chỉ vì bật auto-review; người vận hành bấm **Tạo index từ bản đã duyệt**, rồi **Lấy evidence**. API `POST /api/pipeline` thêm boolean `auto_approve` mặc định false. `POST /api/pipeline/{id}/auto-review` chỉ xử lý bản pending của phiên crawl, kiểm lại điều kiện và revision trong transaction; bấm lại không duyệt trùng.

**Tạo phiên mới** giữ bộ key/model đang chọn; chỉ xóa phạm vi/bộ tài liệu và tắt tự duyệt. Lần dùng đầu vẫn mặc định BTC. Lựa chọn model/key group (không chứa key) được nhớ trong sessionStorage. Trước chạy, UI kiểm tra thiếu key theo đúng các bước cần dùng; không tự đổi sang nhà cung cấp khác. Chỉ khi server trả chính xác lỗi phiên nội bộ đã đổi, UI lấy CSRF mới và thử lại một lần; các lỗi 401/provider không được retry bằng cơ chế này.

Job mới lưu owner_pid. Khởi tạo app khác không đánh dấu job của server còn sống là gián đoạn. Job legacy không có PID không được suy diễn là đã dừng chỉ từ việc import ứng dụng.

Nút **Tải evidence JSON cho agent** dùng `GET /api/pipeline/{id}/evidence/download`, trả file đính kèm từ server. Endpoint kiểm lại trạng thái duyệt và độ mới của index; tài liệu bị thu hồi hoặc snapshot không còn hợp lệ sẽ chặn tải.
