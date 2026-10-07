"""Evidence selection must be supported by selected source segments."""

import json

from document_check import evidence_error, evidence_segments, correction_task


def test_year_in_another_segment_is_rejected_without_mutating_claims():
    segments = [{"text": "Năm 2020 tăng trưởng 5%."}, {"text": "Năm 2024 đạt 8%."}]
    result = {"evidence_ids": [0], "years": [2024]}
    original = json.dumps(result)
    assert evidence_error(result, segments) == "Semantic check nêu năm không có trong quote"
    task = "Instructions\n" + json.dumps({"segments": segments})
    assert evidence_segments(task) == segments
    correction = correction_task(task, result, segments)
    assert '"0": [2020]' in correction and '"1": [2024]' in correction
    assert json.dumps(result) == original
    assert evidence_error({"evidence_ids": [1], "years": [2024]}, segments) is None


def test_invalid_ids_and_empty_evidence_cannot_support_years():
    segments = [{"text": "No dates"}]
    for ids in ([-1], [1], [True], list(range(9))):
        assert "ID" in evidence_error({"evidence_ids": ids, "years": []}, segments)
    assert evidence_error({"evidence_ids": [], "years": [2024]}, segments)
    assert evidence_error({"evidence_ids": [0], "years": []}, segments) is None
