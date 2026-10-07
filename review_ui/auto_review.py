"""Opt-in approval policy; extraction scores never imply factual verification."""

from quality import assess

POLICY = "auto-review-v1"
ACTOR = "Hệ thống · " + POLICY


def blockers(doc):
    reasons = []
    if doc["status"] != "pending" or doc["revision"] != 1:
        reasons.append("Chỉ tự duyệt bản mới, chưa chỉnh sửa và đang chờ duyệt.")
    quality = assess(doc)
    if not doc.get("chunks") or quality["score"] < 90:
        reasons.append("Không có đoạn nội dung hoặc chất lượng trích xuất dưới 90.")
    if any(f["severity"] in ("warning", "error") for f in quality["findings"]):
        reasons.append("Có cảnh báo hoặc lỗi trích xuất cần người kiểm tra.")
    assessment = doc.get("crawl", {}).get("assessment") or {}
    if (
        doc.get("source_kind") != "web"
        or not doc.get("source_url")
        or assessment.get("status") != "review"
        or assessment.get("subject_match") is not True
        or (
            assessment.get("country_gate_required")
            and assessment.get("geography_match") is not True
        )
        or assessment.get("verification") != "model_assessed_quotes_checked_not_fact_verified"
        or not assessment.get("evidence_quotes")
        or assessment.get("parse_partial")
        or assessment.get("input_truncated")
    ):
        reasons.append("Thiếu đánh giá AI hợp lệ, không khớp phạm vi hoặc bằng chứng chưa đầy đủ.")
    return reasons


def approval_mode(doc):
    latest = next(
        (entry for entry in reversed(doc.get("audit", [])) if entry.get("action") == "approve"), {}
    )
    return "automatic" if latest.get("approval_mode") == "automatic" else "manual"
