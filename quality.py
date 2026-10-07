"""Explainable extraction checks. Scores are not probabilities of factual truth."""

import re


def assess(doc):
    findings = []

    def add(code, severity, message, penalty=0, snippet="", locator=None):
        findings.append(
            {
                "code": code,
                "severity": severity,
                "message": message,
                "penalty": penalty,
                "snippet": snippet,
                "locator": locator or {},
            }
        )

    text = doc["text"]
    if not text.strip():
        add(
            "empty",
            "error",
            "Không trích được chữ. PDF scan cần OCR hoặc bổ sung bản text đã kiểm.",
            100,
        )
    elif len(text.split()) < 30:
        add("short", "warning", "Nội dung rất ngắn; kiểm tra nguồn có bị thiếu phần hay không.", 15)
    if doc.get("partial"):
        add(
            "partial",
            "error",
            "Parser chỉ xử lý một phần nguồn. Cần nhập bản đầy đủ trước khi duyệt.",
            40,
        )
    for warning in doc.get("parser_warnings", []):
        add("parser_warning", "warning", str(warning), 5)
    damaged = re.search(r"\ufffd|[\x00-\x08\x0b\x0c\x0e-\x1f]", text)
    if damaged:
        start = max(0, damaged.start() - 35)
        add(
            "encoding",
            "warning",
            "Có ký tự lỗi hoặc điều khiển. Đối chiếu văn bản gốc.",
            25,
            text[start : damaged.end() + 50],
            {"start": damaged.start(), "end": damaged.end()},
        )
    directive = re.search(
        r"ignore\s+(all\s+)?(previous|prior)\s+instructions|bỏ qua.{0,25}(chỉ dẫn|hướng dẫn)|system\s*prompt",
        text,
        re.I,
    )
    if directive:
        add(
            "instruction",
            "warning",
            "Đoạn này có dạng chỉ dẫn cho AI; chỉ coi là dữ liệu nguồn, cần người kiểm.",
            10,
            text[max(0, directive.start() - 30) : directive.end() + 80],
            {"start": directive.start(), "end": directive.end()},
        )
    sensitive = re.search(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:api[_ -]?key|password|mật khẩu)\s*[:=]\s*\S+",
        text,
        re.I,
    )
    if sensitive:
        add(
            "sensitive",
            "warning",
            "Có dấu hiệu thông tin nhạy cảm. Xác nhận quyền sử dụng và loại bỏ bí mật trước khi duyệt.",
            20,
            "[Không hiển thị lại giá trị nghi nhạy cảm]",
            {"start": sensitive.start(), "end": sensitive.end()},
        )
    if doc.get("duplicate_of"):
        add(
            "duplicate",
            "warning",
            "Nội dung gốc trùng tài liệu đã nhập. Kiểm tra phiên bản để tránh lập chỉ mục lặp.",
            10,
        )
    if doc.get("time_sensitive") and not doc.get("effective_from"):
        add(
            "effective_date",
            "error",
            "Tài liệu có thời hạn cần ngày bắt đầu hiệu lực do người duyệt xác nhận.",
            25,
        )
    if not doc.get("source_url"):
        add(
            "source_verification",
            "info",
            "Nguồn là bản tải lên; cần đối chiếu đơn vị phát hành và thẩm quyền nội dung.",
        )
    add(
        "factual_review",
        "info",
        "Chưa xác minh tính đúng của nội dung. Kiểm tra tự động chỉ phát hiện một số lỗi trích xuất và metadata.",
    )
    score = max(0, 100 - sum(f["penalty"] for f in findings))
    label = (
        "Cần sửa"
        if any(f["severity"] == "error" for f in findings)
        else (
            "Cần đối chiếu"
            if any(f["severity"] == "warning" for f in findings)
            else "Sẵn sàng để người duyệt kiểm"
        )
    )
    return {
        "score": score,
        "label": label,
        "findings": findings,
        "factual_confidence": "unverified",
        "method": "extraction-rules-v1",
        "explanation": "Điểm quy tắc 0–100, trừ theo cảnh báo đã liệt kê; chưa hiệu chỉnh và không phải xác suất đúng.",
    }
