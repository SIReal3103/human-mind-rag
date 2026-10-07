"""Bounded, non-generation key probes and public diagnostics; no response body leaks."""

from datetime import datetime, timezone
import json
import re
import ssl
import urllib.error
import urllib.request

import certifi

PROVIDER_NAMES = {
    "btc": "BTC",
    "openai": "OpenAI",
    "google": "Google / Gemini",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
}
KEY_LABELS = {
    "btc": "BTC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
STAGE_LABELS = {
    "authentication": "Kiểm tra key",
    "planner": "Lập kế hoạch",
    "search": "Tìm nguồn",
    "check": "Kiểm nội dung / xếp nguồn",
    "embedding": "Embedding",
    "evidence": "Kiểm phạm vi / rerank evidence",
}
PROBE_URLS = {
    "btc": "https://api.thucchien.ai/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
    "anthropic": "https://api.anthropic.com/v1/models?limit=1",
    "deepseek": "https://api.deepseek.com/models",
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def diagnostic(provider, stage, status, code=None):
    messages = {
        "ok": "Lời gọi thành công. Kết quả chỉ xác nhận bước vừa kiểm tra.",
        "invalid_key": "Key bị từ chối xác thực. Thay key của provider này rồi kiểm tra lại.",
        "permission_denied": "Không đủ quyền truy cập API/model; chưa thể kết luận key hỏng.",
        "quota_exceeded": "Hết hạn mức hoặc chưa có billing khả dụng; không đồng nghĩa key hỏng.",
        "rate_limited": "Bị giới hạn lượt gọi hoặc quota; không đồng nghĩa key hỏng.",
        "network_error": "Không kết nối được API. Kiểm tra mạng/HTTPS; chưa xác định key hợp lệ hay không.",
        "capability_unverified": "Khả năng BTC chưa được smoke-test theo repo gốc; pipeline giữ nguyên gate.",
        "unsupported": "Endpoint kiểm tra chưa được hỗ trợ; chưa xác định key hợp lệ hay không.",
        "request_failed": "Yêu cầu không hoàn tất. Kiểm tra cấu hình, model và trace; chưa kết luận key hỏng.",
        "model_unavailable": "Model không tồn tại hoặc key chưa được cấp quyền model này. Chọn model khác trong cùng bộ key.",
        "invalid_request": "API từ chối cấu trúc hoặc tham số yêu cầu; đây không phải kết luận key hỏng.",
        "invalid_output": "Model trả nội dung không khớp hợp đồng dữ liệu. Không chấp nhận nội dung này; xem bước lỗi và thử lại.",
    }
    if status not in messages or provider not in PROVIDER_NAMES or stage not in STAGE_LABELS:
        raise ValueError("Diagnostic không hợp lệ")
    return {
        "provider": provider,
        "stage": stage,
        "provider_name": PROVIDER_NAMES[provider],
        "key_label": KEY_LABELS[provider],
        "stage_label": STAGE_LABELS[stage],
        "status": status,
        "code": code,
        "message": messages[status],
        "checked_at": timestamp(),
    }


def error_diagnostic(provider, stage, error):
    if isinstance(error, ProviderError):
        return diagnostic(provider, stage, error.status, error.code)
    message = str(error)
    if message == "Planner tự thay đổi năm đã trích từ input":
        result = diagnostic(provider, stage, "invalid_output", "PLANNER_YEAR_MISMATCH")
        result["message"] = (
            "Model lập kế hoạch trả năm khác phạm vi. Đây là lỗi kiểm tra kế hoạch, không phải lỗi key. Dùng khoảng năm cụ thể hoặc chạy lại với phạm vi đã quy đổi."
        )
        return result
    semantic_errors = {
        "Semantic check nêu năm không có trong quote": "Model nêu năm không xuất hiện trong đoạn bằng chứng đã chọn. Đánh giá AI chưa được chấp nhận; người duyệt cần đối chiếu bản gốc. Đây không phải lỗi key.",
        "Semantic check nêu ID bằng chứng không có trong bản parse": "Model chọn mã bằng chứng không có trong văn bản đã parse. Đánh giá AI chưa được chấp nhận; cần đối chiếu bản gốc. Đây không phải lỗi key.",
    }
    if message in semantic_errors:
        result = diagnostic(provider, stage, "invalid_output", "EVIDENCE_VALIDATION_FAILED")
        result["message"] = semantic_errors[message]
        return result
    match = re.fullmatch(r"AI_HTTP_(\d{3}): request failed; provider body omitted", message)
    if match:
        code = int(match[1])
        return diagnostic(
            provider,
            stage,
            {401: "invalid_key", 403: "permission_denied", 429: "rate_limited"}.get(
                code, "request_failed"
            ),
            f"HTTP_{code}",
        )
    if message == "AI_NETWORK_ERROR: request failed":
        return diagnostic(provider, stage, "network_error", "AI_NETWORK_ERROR")
    gate = re.fullmatch(
        r"CAPABILITY_UNVERIFIED: (BTC_(?:STRUCTURED|SEARCH|EMBEDDING|EMBEDDING_BATCH)_VERIFIED); smoke-test BTC before enabling",
        message,
    )
    if gate:
        return diagnostic(provider, stage, "capability_unverified", gate[1])
    return diagnostic(provider, stage, "request_failed", "REQUEST_FAILED")


class ProviderError(ValueError):
    """Only closed diagnostics may cross the credential-bearing HTTP boundary."""

    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(f"{status}: {code}")


def describe(result):
    return f"{result['stage_label']} · {result['provider_name']} · {result['key_label']} · {result['code'] or result['status']}: {result['message']}"


class NoProbeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Key probe redirect blocked")


def classify_probe(provider, code, body):
    """Map allowlisted machine codes only; never persist provider messages or key fragments."""
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    error = error if isinstance(error, dict) else {}
    reasons = [error.get("code"), error.get("type")]
    details = error.get("details", [])
    if isinstance(details, list):
        reasons += [item.get("reason") for item in details if isinstance(item, dict)]
    if code == 401 or any(
        value in ("API_KEY_INVALID", "invalid_api_key", "authentication_error") for value in reasons
    ):
        status = "invalid_key"
    elif (
        any(value in ("insufficient_quota", "billing_hard_limit_reached") for value in reasons)
        or code == 402
    ):
        status = "quota_exceeded"
    elif code == 403:
        status = "permission_denied"
    elif code == 429:
        status = "rate_limited"
    elif code in (404, 405):
        status = "unsupported"
    elif (
        code == 200
        and isinstance(payload, dict)
        and (isinstance(payload.get("data"), list) or isinstance(payload.get("models"), list))
    ):
        status = "ok"
    else:
        status = "request_failed"
    result = diagnostic(provider, "authentication", status, f"HTTP_{code}")
    if status == "ok":
        result["message"] = (
            "API chấp nhận key khi liệt kê model. Chưa xác nhận quyền tìm web, tạo nội dung, embedding hoặc Veo."
        )
    return result


def check_key(provider, key):
    if provider not in PROBE_URLS:
        raise ValueError("Provider không hỗ trợ kiểm tra key")
    headers = {"Accept": "application/json"}
    if provider == "google":
        headers["x-goog-api-key"] = key
    elif provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = "Bearer " + key
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoProbeRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
    )
    request = urllib.request.Request(PROBE_URLS[provider], headers=headers)
    try:
        with opener.open(request, timeout=20) as response:
            code, body = response.status, response.read(2_000_001)
    except urllib.error.HTTPError as error:
        try:
            code, body = error.code, error.read(2_000_001)
        except OSError:
            return diagnostic(provider, "authentication", "network_error", "NETWORK_ERROR")
        finally:
            error.close()
    except (urllib.error.URLError, OSError, ValueError):
        return diagnostic(provider, "authentication", "network_error", "NETWORK_ERROR")
    if len(body) > 2_000_000:
        return diagnostic(provider, "authentication", "request_failed", "RESPONSE_TOO_LARGE")
    return classify_probe(provider, code, body)
