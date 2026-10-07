# Kiểm chứng upstream Scope Data Bot

Ngày kiểm: 07/10/2026, máy local macOS. Repository: [Qyroven/scope-data-bot](https://github.com/Qyroven/scope-data-bot), commit `cb37446a00c6283cbb596df524885cfcb08a9fe7`. Clone được kiểm tại `/path/to/workspace/scope-data-bot`; không sửa source upstream. `git diff --name-only` sau kiểm tra không có output.

## Kết quả

| Kiểm tra | Kết quả thực tế | Phạm vi chứng minh |
| --- | --- | --- |
| Runtime local | Python 3.12.10, SQLite 3.49.1, Ruff 0.16.10 | Môi trường chạy lần kiểm này |
| Dependency consistency | `uv pip check`: 45 packages, không xung đột | Packages đã cài tương thích theo metadata dependency |
| Unit suite, profile OpenAI nguyên bản, không key, chặn network | 94 tests: 93 pass, 1 skip; exit 0; 1.173 giây; 0 connection attempts | Regression offline với fixtures/mocks; không chứng minh inference OpenAI hoặc BTC |
| Unit suite, ép profile BTC, gate đóng | 94 tests: 85 pass, 5 failures, 3 errors, 1 skip; exit 1; 1.677 giây | Phát hiện suite phụ thuộc profile mặc định; gate BTC đang chặn đường chưa được xác minh |
| Ruff quét nguyên thư mục | Lint exit 1, 22 E902; format exit 2 | Lỗi đọc file AppleDouble `._*.py` không phải UTF-8 trên ổ đĩa macOS |
| Ruff trên file Python được Git theo dõi | Lint pass; format pass, 22 files already formatted; exit 0 | Code Python tracked tại commit được kiểm; không bỏ qua lỗi code đã thấy |
| CLI `--help` trong temp CWD | Exit 0 | Import, tạo parser và help hoạt động |
| CLI thiếu input / dimensions bằng 0 | Cả hai exit 2 với lỗi argparse tương ứng; temp CWD không có artifact | Validation đối số trước khi vào ingest |
| Docling local | Chưa cài, một test opt-in bị skip | Chưa xác minh parse/OCR Docling trên máy local |

Đã đọc README, `pyproject.toml`, `requirements-dev.txt`, workflow CI, các test gateway/embedding/cache và CLI trước khi chạy. `.env.local` không tồn tại ở clone; chỉ kiểm sự tồn tại, không đọc nội dung dotenv. Các lời gọi provider trong test được mock; dữ liệu test là fixtures có nhãn. Không chạy scope ingestion thật, crawl thật hoặc inference trả phí; không bật capability gate. Dòng `[crawl]` trong stdout unit test đến từ workflow chạy với fetch/discovery đã được mock, không phải bằng chứng crawl trực tiếp.

## Lệnh local và lỗi cần giữ lại

CWD cho các lệnh dưới đây là `/path/to/workspace/scope-data-bot` trừ các CLI smoke có CWD tạm. Python dùng `/path/to/user/.cache/rag-review-venv/bin/python`.

```bash
/path/to/user/.cache/rag-review-venv/bin/python --version
uv pip check --python /path/to/user/.cache/rag-review-venv/bin/python
/path/to/user/.cache/rag-review-venv/bin/ruff --version
/path/to/user/.cache/rag-review-venv/bin/ruff check --no-cache .
/path/to/user/.cache/rag-review-venv/bin/ruff format --no-cache --check .
git ls-files -z '*.py' '*.pyi' '*.ipynb' | xargs -0 /path/to/user/.cache/rag-review-venv/bin/ruff check --no-cache
git ls-files -z '*.py' '*.pyi' '*.ipynb' | xargs -0 /path/to/user/.cache/rag-review-venv/bin/ruff format --no-cache --check
```

Lệnh Ruff nguyên thư mục gặp 22 Python metadata sidecars không hợp lệ; format còn báo sidecar `._README.md`, đồng thời báo 23 file thật đã đúng format. `git status`/`git ls-tree` cũng báo `non-monotonic index` với file `.git/objects/pack/._pack-171a3700cf94649934a9f985bf6caa986b1ad52a.idx`. Đây là hiện trạng clone trên volume local. Không xóa file, sửa Git hoặc thêm ignore để che lỗi; kiểm source tracked riêng vẫn thành công. Không kết luận clone “clean” vì các sidecar untracked còn tồn tại.

Lệnh đầu kiểm suite với BTC gate đóng:

```bash
env -u BTC_API_KEY -u OPENAI_API_KEY -u THUCCHIEN_API_KEY \
  -u BTC_STRUCTURED_VERIFIED -u BTC_SEARCH_VERIFIED \
  -u BTC_EMBEDDING_VERIFIED -u RUN_PARSER_SMOKE \
  AI_PROVIDER=btc PYTHONDONTWRITEBYTECODE=1 \
  /path/to/user/.cache/rag-review-venv/bin/python -m unittest discover -p 'test_*.py'
```

Tám trường hợp không đạt trong lần này:

| Test | Kết quả và nguyên nhân thấy trực tiếp |
| --- | --- |
| `test_embedding_response_reordered_and_duplicate_index` | Error: `BTC_EMBEDDING_VERIFIED` đóng trước khi đến response mock |
| `test_openai_destination_and_citation_evidence` | Error: `BTC_SEARCH_VERIFIED` đóng; test đặt kỳ vọng URL OpenAI |
| `test_vietnamese_query_is_sent_as_utf8_separate_from_instructions` | Error: `BTC_SEARCH_VERIFIED` đóng |
| `test_identical_embedding_inputs_reused_across_scopes_with_separate_provenance` | Failure: số lần embed fixture là 0 thay vì 1; fixture ban đầu dùng provider môi trường, nhưng test giả định chuyển từ OpenAI sang BTC |
| `test_legacy_scoped_cache_is_promoted_without_an_api_call` | Failure: legacy cache fixture hardcode provider `openai`, khác runtime BTC |
| `test_text_links_without_search_evidence_are_rejected` | Failure: kỳ vọng lỗi `web_search_call`, thực tế dừng trước ở capability gate |
| `test_incomplete_search_never_accepts_citations` | Failure: kỳ vọng lỗi `incomplete`, thực tế dừng trước ở capability gate |
| `test_provider_change_invalidates_index_before_api_request` | Failure: test giả định index ban đầu OpenAI rồi đổi BTC; khi cả hai đều BTC không có provider change, và structured gate chặn bước sau |

Nguồn xác minh các giả định fixture: `test_data_pipeline.py:117–158`, `test_review_regressions.py:154–163`, `gateway.py:37–39,110`, `data_pipeline.py:125`. Các kết quả này không chứng minh gateway BTC lỗi. Chưa có bộ suite chạy đầy đủ cho profile BTC với transport được mock riêng và gate được kiểm một cách độc lập.

Lần thứ hai giữ profile mà suite upstream thiết kế, xóa key khỏi process và chặn kết nối mạng tại socket. Không sửa source hay cấu hình ứng dụng:

```bash
env -u BTC_API_KEY -u OPENAI_API_KEY -u THUCCHIEN_API_KEY \
  -u BTC_STRUCTURED_VERIFIED -u BTC_SEARCH_VERIFIED \
  -u BTC_EMBEDDING_VERIFIED -u BTC_EMBEDDING_BATCH_VERIFIED \
  -u RUN_PARSER_SMOKE AI_PROVIDER=openai PYTHONDONTWRITEBYTECODE=1 \
  /path/to/user/.cache/rag-review-venv/bin/python - <<'PY'
import runpy
import socket
import sys

blocked_attempts = []
def deny_network(*args, **kwargs):
    blocked_attempts.append('outbound connection')
    raise AssertionError('Offline validation forbids network connections')
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network
sys.argv = ['unittest', 'discover', '-p', 'test_*.py']
try:
    runpy.run_module('unittest', run_name='__main__')
finally:
    print(f'Offline network guard: {len(blocked_attempts)} connection attempts', file=sys.stderr)
PY
```

Kết quả: `Ran 94 tests in 1.173s`, `OK (skipped=1)`, `Offline network guard: 0 connection attempts`. Không nâng kết quả này thành chứng minh chất lượng inference, OCR hoặc dữ liệu thật.

CLI smoke dùng `subprocess.run` với temp directory riêng, timeout 15 giây, `AI_PROVIDER=btc`, `PYTHONDONTWRITEBYTECODE=1`; loại bỏ `BTC_API_KEY`, `OPENAI_API_KEY`, `THUCCHIEN_API_KEY`, `RUN_PARSER_SMOKE` và mọi biến `BTC_*_VERIFIED` khỏi môi trường con. Ba argv đã chạy:

```text
/path/to/user/.cache/rag-review-venv/bin/python /path/to/workspace/scope-data-bot/data_bot.py --help
/path/to/user/.cache/rag-review-venv/bin/python /path/to/workspace/scope-data-bot/data_bot.py
/path/to/user/.cache/rag-review-venv/bin/python /path/to/workspace/scope-data-bot/data_bot.py --scope "offline argument validation" --dimensions 0
```

Ở dạng shell, cần quote đường dẫn có khoảng trắng; danh sách trên là argv được truyền trực tiếp, không qua shell. Chỉ chạy help/đối số không hợp lệ sau khi kiểm `data_bot.py`; không chạy scope hợp lệ. Help còn có mô tả key OpenAI cũ dù đang chọn profile BTC.

## Bằng chứng GitHub và phạm vi sử dụng

GitHub API tại thời điểm kiểm trả về:

- Repository tạo `2026-10-06T17:08:05Z`, push gần nhất `2026-10-06T18:18:28Z`; không archived, không phải fork; 0 stars, 0 forks. Đây là metadata tại thời điểm kiểm, không phải điểm chất lượng.
- Commit được kiểm: `cb37446a00c6283cbb596df524885cfcb08a9fe7`, ngày `2026-10-06T18:18:28Z`, message `Reuse embeddings and streamline chunk generation with provenance intact (#3)`.
- Endpoint tags và releases đều trả `[]`; chưa thấy phiên bản phát hành/tag trên GitHub.
- `licenseInfo: null`; endpoint `/license` trả 404; tracked tree không có LICENSE/COPYING/NOTICE. Chưa có bằng chứng giấy phép cho phép sao chép/phân phối source. Việc public repository và clone được không tự xác lập giấy phép tái sử dụng.
- [CI Offline tests của đúng SHA](https://github.com/Qyroven/scope-data-bot/actions/runs/37510295504) completed/success. Ba jobs `test (3.12)`, `test (3.14)`, `parser-runtime` đều success.
- Logs CI: Python 3.12 chạy 94 tests, 1 skip, 1.192 giây; Python 3.14 chạy 94 tests, 1 skip, 1.063 giây. Cả hai Ruff pass, 23 files already formatted. Job parser-runtime chạy 1 test trong 10.757 giây, job success.

Các lệnh GitHub read-only đã dùng:

```bash
gh repo view Qyroven/scope-data-bot --json nameWithOwner,url,createdAt,updatedAt,pushedAt,isArchived,isFork,licenseInfo,stargazerCount,forkCount,primaryLanguage,defaultBranchRef
gh api repos/Qyroven/scope-data-bot/commits/cb37446a00c6283cbb596df524885cfcb08a9fe7 --jq '{sha, commit_date: .commit.committer.date, message: .commit.message}'
gh api repos/Qyroven/scope-data-bot/tags --jq 'map({name, commit: .commit.sha})'
gh api repos/Qyroven/scope-data-bot/releases --jq 'map({tag_name, published_at, draft, prerelease})'
gh api 'repos/Qyroven/scope-data-bot/actions/runs?head_sha=cb37446a00c6283cbb596df524885cfcb08a9fe7' --jq '.workflow_runs | map({id,name,head_sha,status,conclusion,html_url,created_at,updated_at})'
gh api repos/Qyroven/scope-data-bot/actions/runs/37510295504/jobs --jq '.jobs | map({name,status,conclusion,started_at,completed_at,html_url,steps: [.steps[] | {name,conclusion}]})'
gh api repos/Qyroven/scope-data-bot/license --jq '{name,path,license: .license.spdx_id}'
gh run view 37510295504 --repo Qyroven/scope-data-bot --log | rg 'Ran [0-9]+ tests?|OK \(skipped=|All checks passed|files already formatted|All installed packages are compatible'
```

## Giới hạn đã thấy đối với trang duyệt RAG

README mô tả CLI một người dùng: chưa UI, tenant ACL hoặc egress sandbox cho dịch vụ crawl công khai; chưa hard memory sandbox và chưa tổng giới hạn chi phí bằng tiền/cancel service. Generic documents trạng thái `review` có thể được index và trả về kèm cờ review; `ready_partial` chỉ chứng minh có index dùng được. Vì vậy upstream hiện chưa đáp ứng bất biến của trang mới: tài liệu pending/rejected tuyệt đối không vào nguồn agent truy hồi.

README tự ghi profile live đã dùng là OpenAI; profile BTC chưa chạy key thật và gates đóng. Evidence/benchmark live được giữ local ở upstream, không có trong clone này để xác minh. CI parser-runtime là chuyển DOCX fixture không tải model/OCR, không chứng minh PDF scan/bảng tiếng Việt ngoài đời được đọc đúng.

Chưa đo retrieval recall/groundedness trên corpus nghiệp vụ, độ đúng OCR, latency/cost qua BTC, chất lượng review/confidence, đa người dùng, authorization của web app hoặc toàn luồng upload → duyệt → agent. Không có kết luận “production ready”, calibrated confidence hoặc tỷ lệ chất lượng sản phẩm từ các test offline trên.

## Kiểm tích hợp bổ sung của trang duyệt

Đây là kết quả của ứng dụng mới dưới `chung-khao/rag-review`, tách khỏi kết quả upstream trên. Đã thêm `tests/test_workflow.py` và chạy:

```bash
PYTHONDONTWRITEBYTECODE=1 /path/to/user/.cache/rag-review-venv/bin/python -m pytest -q tests/test_workflow.py
/path/to/user/.cache/rag-review-venv/bin/ruff check --no-cache tests/test_workflow.py
/path/to/user/.cache/rag-review-venv/bin/ruff format --no-cache --check tests/test_workflow.py
```

CWD: `/path/to/workspace/aitc2026-team-468-delta-mind/chung-khao/rag-review`. Kết quả lần cuối: **17 tests và 20 subtests pass**, 9.93 giây, exit 0. Ruff lint và format pass. Một cảnh báo không bị ẩn: Starlette báo adapter TestClient dùng `httpx` đã deprecated và khuyên `httpx2`; các assertions vẫn đạt trên dependency hiện cài.

Các ca chạy API thật bằng TestClient, SQLite/file thật và adapter parser/chunker subprocess, không mock ingestion hoặc index: pending/rejected bị loại khỏi search/export; sửa làm approval cũ hết hiệu lực; cảnh báo cần boolean acknowledgement; lỗi metadata không thể override; collection và kỳ `[from,to)` được lọc trước limit; compact/week-date bị trả 422; bản approved bất biến; callback duyệt lặp bị chặn; thu hồi loại ngay evidence; restart giữ dữ liệu/audit và đổi CSRF; đầu vào FTS/SQL không thay storage/scope; chặn revision chồng hiệu lực; reject/reopen cần sự kiện rõ; upload PDF hai trang có locator thật; PDF không có text ở pending cho đến khi có reviewed text; MIME/metadata sai bị chặn; URL private/metadata/scheme/credential bị từ chối; Host/Origin/CSRF bảo vệ mutation. PDF và text ở đây là fixtures được tạo riêng trong test, không phải tài liệu production hoặc phép đo độ đúng OCR.

Mỗi test dùng `tempfile.TemporaryDirectory` trên filesystem native với `RAG_REVIEW_DATA` trỏ vào đó, không tạo DB ở volume repo. Theo `app.py:create_app`, đường dữ liệu mặc định của trang là `~/.local/share/delta-mind-rag-review/<workspace-path-sha12>` và có thể cấu hình bằng `RAG_REVIEW_DATA`; đây là lựa chọn tương thích lưu trữ của ứng dụng mới. Lỗi exFAT `SQLITE_READONLY_DBMOVED` do controller tái hiện trước khi đổi đường mặc định không được tính thành một phép kiểm độc lập trong báo cáo này.
