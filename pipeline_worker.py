"""Isolated upstream execution. Credentials arrive through stdin, never artifacts."""

from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingestion import _require_upstream
from api_routing import StageRouter, read_events
from model_catalog import configuration
from auto_review import approval_mode


def safe_error(error):
    message = str(error)
    known = {
        "Planner tự thay đổi năm đã trích từ input": "Lập kế hoạch: model trả năm khác phạm vi đã yêu cầu. Đây là lỗi kiểm tra kế hoạch, không phải lỗi key. Chạy lại với khoảng năm cụ thể.",
        "Planner tự chọn mẫu số không có trong input": "Lập kế hoạch: model tự chọn mẫu số không có trong yêu cầu. Làm rõ mẫu số rồi thử lại; không phải lỗi key.",
        "Model output không đúng schema": "Model trả cấu trúc dữ liệu không hợp lệ; nội dung chưa được chấp nhận. Thử lại hoặc đổi model.",
        "Scope lớn hơn 31 năm: cần thu hẹp phạm vi.": "Phạm vi vượt 31 năm. Chia thành các phiên nhỏ hơn.",
    }
    if message in known:
        return known[message]
    http = re.fullmatch(r"AI_HTTP_(\d{3}): request failed; provider body omitted", message)
    if http:
        code = http[1]
        hint = {
            "401": "Key không được chấp nhận. Kiểm tra key của provider đã chọn trong Cấu hình API key.",
            "403": "Provider từ chối quyền truy cập. Kiểm tra quyền tài khoản và model.",
            "429": "Provider giới hạn lượt gọi hoặc hạn mức thanh toán. Kiểm tra quota/billing trước khi thử lại.",
        }.get(code, "Kiểm tra trạng thái dịch vụ và quyền sử dụng model trước khi thử lại.")
        return f"AI_HTTP_{code}: {hint}"
    if message == "AI_NETWORK_ERROR: request failed":
        return "AI_NETWORK_ERROR: Không kết nối được provider. Kiểm tra mạng và chứng chỉ HTTPS của Python."
    capability = re.fullmatch(
        r"CAPABILITY_UNVERIFIED: (BTC_(?:STRUCTURED|SEARCH|EMBEDDING|EMBEDDING_BATCH)_VERIFIED); smoke-test BTC before enabling",
        message,
    )
    if capability:
        return f"CAPABILITY_UNVERIFIED: {capability[1]}. Repo gốc yêu cầu kiểm thử khả năng BTC trước khi bật cờ này; pipeline không tự bỏ qua kiểm tra."
    if message in ("Chưa có key cho AI_PROVIDER=btc", "Chưa có key cho AI_PROVIDER=openai"):
        return message + ". Mở Cấu hình API key và lưu key của provider đã chọn."
    if message == "Embedding model/index contract mismatch":
        return "Phản hồi embedding không khớp model hoặc số lượng yêu cầu. Index chưa được tạo."
    return f"Pipeline không hoàn tất ({type(error).__name__}). Kiểm tra trace, nguồn và cấu hình phiên."


def prepare_snapshot(folder, scope):
    from trace import TraceStore

    snapshot = json.loads((folder / "approved.json").read_text())
    run = folder / "published"
    (run / "parsed").mkdir(parents=True)
    (run / "raw").mkdir()
    trace = TraceStore(run)
    (run / "approval.json").write_text(json.dumps(snapshot, ensure_ascii=False))
    automatic_count = sum(approval_mode(d) == "automatic" for d in snapshot["documents"])
    review_stage = "approval" if automatic_count else "human-review"
    root = trace.artifact("approval.json", parents=[], stage=review_stage)
    for doc in snapshot["documents"]:
        if doc["status"] != "approved":
            raise ValueError("Unapproved snapshot")
        raw = (folder / "originals" / doc["id"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != doc["source_sha256"]:
            raise ValueError("Original integrity failure")
        raw_path = "raw/" + doc["id"]
        (run / raw_path).write_bytes(raw)
        raw_node = trace.artifact(
            raw_path,
            parents=[root["id"]],
            stage="automatic-review" if approval_mode(doc) == "automatic" else "human-review",
        )
        parsed = {
            "title": doc["title"],
            "text": doc["text"],
            "url": doc["source_url"],
            "parser": doc["parser"],
            "raw_sha256": doc["source_sha256"],
            "raw_path": raw_path,
            "status": "review",
            "trace_id": root["id"],
            "parse_warnings": doc["parser_warnings"],
            "parse_partial": doc["partial"],
            "assessment": {
                ("automatic_approval" if approval_mode(doc) == "automatic" else "human_approval"): {
                    "document_id": doc["id"],
                    "revision": doc["revision"],
                    "audit": doc["audit"],
                },
                "factual_confidence": "unverified",
            },
        }
        name = "parsed/" + doc["id"] + ".json"
        (run / name).write_text(json.dumps(parsed, ensure_ascii=False))
        if (
            not doc["edited"]
            and doc.get("segments")
            and all(s.get("locator", {}).get("kind") == "page" for s in doc["segments"])
        ):
            parsed["pages"] = [
                {"page": s["locator"]["page"], "text": s["text"]} for s in doc["segments"]
            ]
            (run / name).write_text(json.dumps(parsed, ensure_ascii=False))
        trace.artifact(name, parents=[raw_node["id"]], stage="save")
    (run / "scope.json").write_text(
        json.dumps({"brief": scope, "planner": review_stage, "ambiguities": []})
    )
    (run / "report.json").write_text(
        json.dumps(
            {
                "status": "approved_snapshot" if automatic_count else "human_approved",
                "counts": {
                    "human_approved": len(snapshot["documents"]) - automatic_count,
                    "automatically_approved": automatic_count,
                },
            }
        )
    )
    return run


def execute(request):
    sys.path.insert(0, _require_upstream()["path"])
    provider = request.get("provider", "btc")
    os.environ["AI_PROVIDER"] = provider
    os.environ["BTC_API_KEY" if provider == "btc" else "OPENAI_API_KEY"] = request.pop("key", "")
    folder = Path(request["folder"])
    credentials = request.pop("credentials", {})
    config = (
        configuration(request["key_group"], request["stage_models"])
        if request.get("key_group")
        else None
    )
    router = (
        StageRouter(
            request["stage_providers"],
            credentials,
            folder,
            request["api_attempt"],
            config,
            request.get("effective_scope", request.get("scope", "")),
        )
        if request.get("stage_providers")
        else None
    )
    stage = "planner" if request["action"] == "crawl" else "embedding"
    with router if router else nullcontext():
        with router.profile(stage) if router else nullcontext():
            return execute_upstream(request, folder, router)


def execute_upstream(request, folder, router):
    if request["action"] == "crawl":
        from bot import run_bot

        # Match data_bot.py / run-data.sh; "openai" selects gateway web search.
        # The gateway's AI_PROVIDER still determines BTC versus OpenAI.
        report, run = run_bot(
            request.get("effective_scope", request["scope"]),
            folder / "crawl",
            request["max_sources"],
            request["max_pages"],
            request["max_depth"],
            search_provider="openai",
            planner="model",
        )
        return {
            "run": str(run),
            "status": report["status"],
            "error": safe_error(ValueError(report["error"])) if report.get("error") else None,
        }
    from data_pipeline import build, retrieve

    if request["action"] == "build":
        run = prepare_snapshot(folder, request.get("effective_scope", request["scope"]))
        return build(
            run,
            request["model"],
            request["dimensions"],
            request["max_chunks"],
            **({"request_fn": router.embedding_request} if router else {}),
        )
    return retrieve(
        folder / "published",
        request["question"],
        **({"request_fn": router.embedding_request} if router else {}),
    )


if __name__ == "__main__":
    request = json.load(sys.stdin)
    output = Path(request.pop("result"))
    try:
        result = {"ok": True, "result": execute(request)}
    except Exception as error:
        # Provider exceptions can contain response text. Do not persist it or credentials.
        result = {
            "ok": False,
            "error": safe_error(error),
        }
    result["api_events"] = [
        e for e in read_events(request["folder"]) if e.get("attempt") == request.get("api_attempt")
    ]
    output.write_text(json.dumps(result, ensure_ascii=False))
