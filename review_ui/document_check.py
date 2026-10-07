"""Bounded correction of evidence selection; never rewrite a model's claims."""

import json
import re


def evidence_segments(task):
    # Upstream appends one JSON object after its instruction paragraph.
    data = json.loads(task.split("\n", 1)[1])
    return data["segments"]


def evidence_error(result, segments):
    ids = result["evidence_ids"]
    if len(ids) > 8 or any(type(i) is not int or not 0 <= i < len(segments) for i in ids):
        return "Semantic check nêu ID bằng chứng không có trong bản parse"
    years = {
        int(year) for i in ids for year in re.findall(r"\b(?:19|20)\d{2}\b", segments[i]["text"])
    }
    if not set(result["years"]) <= years:
        return "Semantic check nêu năm không có trong quote"
    return None


def correction_task(task, result, segments):
    observed = {
        str(i): sorted({int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", s["text"])})
        for i, s in enumerate(segments)
    }
    return task + (
        "\nKết quả trước không đạt kiểm tra bằng chứng. Hãy đánh giá lại từ bản gốc phía trên, "
        "trả đầy đủ JSON theo schema. Chỉ chọn evidence_ids tồn tại; years chỉ chứa năm dữ liệu "
        "xuất hiện trong CHÍNH những đoạn đã chọn. Không lấy năm từ scope hoặc đoạn khác. "
        "Nếu không có năm dữ liệu được chứng minh, trả years=[] và ghi thiếu trong missing. "
        "Danh sách năm dưới đây chỉ là ký tự quan sát được, không xác nhận đó là năm dữ liệu.\n"
        + json.dumps(
            {
                "previous_selection": {k: result[k] for k in ("evidence_ids", "years")},
                "observed_years_by_segment": observed,
            },
            ensure_ascii=False,
        )
    )
