"""Model/task contracts and the observed relative-date regression, without paid calls."""

from pathlib import Path
import subprocess
import sys

import pytest

from ingestion import _worker_environment
from model_catalog import catalog, configuration, normalize_scope, planner_contract
from model_gateway import destination, text_content, resolve_grounding_url
from pipeline_worker import safe_error
from provider_health import ProviderError, error_diagnostic


def test_relative_years_resolve_once_without_changing_explicit_dates():
    assert (
        normalize_scope("Kinh tế, văn hóa Hà Nam từ 2016 đến nay", "2026-10-07")
        == "Kinh tế, văn hóa Hà Nam từ 2016 đến năm 2026"
    )
    for scope in ("Hà Nam 2020–2024", "Tài liệu văn hóa Hà Nam", "Từ năm 2016 đến năm 2020"):
        assert normalize_scope(scope, "2026-10-07") == scope
    assert normalize_scope("Hà Nam tới hiện tại", "2027-01-01").endswith("2027")


def test_model_selection_uses_one_key_group_and_filters_by_real_capability():
    mixed = {
        "planner": "deepseek-flash",
        "search": "gemini-3.1-flash-lite",
        "check": "gpt-6-luna",
        "embedding": "gemini-embedding-2",
        "evidence": "gemini-2.5-flash",
    }
    external = configuration("external", mixed)
    assert external["stage_providers"] == {
        "planner": "deepseek",
        "search": "google",
        "check": "openai",
        "embedding": "google",
        "evidence": "google",
    }
    assert external["dimensions"] == 3072
    assert set(configuration("btc", mixed)["stage_providers"].values()) == {"btc"}
    for models in (
        {"search": "deepseek-flash"},
        {"embedding": "gpt-6-luna"},
        {"planner": "veo-3.1-generate-001"},
        {"embedding": "text-multilingual-embedding-002"},
        {"unknown": "gpt-6-luna"},
    ):
        with pytest.raises(ValueError):
            configuration("external", models)
    assert configuration()["stage_models"] == catalog()["defaults"]["btc"]


def test_destinations_and_incomplete_responses_are_not_mistaken_for_bad_keys():
    assert (
        destination("btc", "search", "gemini-3.1-flash-lite")
        == "https://api.thucchien.ai/chat/completions"
    )
    assert destination("btc", "search", "gpt-6-luna") == "https://api.thucchien.ai/responses"
    assert (
        destination("openai", "embedding", "text-embedding-3-small")
        == "https://api.openai.com/v1/embeddings"
    )
    assert destination("google", "embedding", "gemini-embedding-2").endswith(
        "/gemini-embedding-2:embedContent"
    )
    with pytest.raises(ValueError):
        destination("google", "planner", "../credentials")
    for payload, provider, model in (
        ({"status": "incomplete"}, "openai", "gpt-6-luna"),
        ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, "google", "gemini-2.5-flash"),
        ({"choices": [{"finish_reason": "length"}]}, "btc", "deepseek-flash"),
    ):
        with pytest.raises(ProviderError) as caught:
            text_content(payload, provider, model)
        assert caught.value.status == "invalid_output"
    result = error_diagnostic(
        "openai", "planner", ValueError("Planner tự thay đổi năm đã trích từ input")
    )
    assert result["status"] == "invalid_output" and "không phải lỗi key" in result["message"]
    assert "không phải lỗi key" in safe_error(
        ValueError("Planner tự thay đổi năm đã trích từ input")
    )


def test_planner_year_constraint_preserves_upstream_validation(tmp_path):
    program = """import sys
sys.path.insert(0,sys.argv[1])
from ingestion import _require_upstream
sys.path.insert(0,_require_upstream()['path'])
from bot import plan_scope
from semantic import PLAN,validate
from model_catalog import normalize_scope,planner_contract
from model_catalog import configuration
from api_routing import StageRouter
from pathlib import Path
import data_pipeline
scope=normalize_scope('Kinh tế, văn hóa Hà Nam từ 2016 đến nay','2026-10-07')
baseline=plan_scope(scope)
assert (baseline['start_year'],baseline['end_year'])==(2016,2026)
task,schema=planner_contract('Original task',PLAN,scope)
assert PLAN['properties']['end_year']=={'type':['integer','null']}
assert schema['properties']['end_year']=={'type':'integer','enum':[2026]}
for year in (2016,2025,None):
    try:validate(year,schema['properties']['end_year'])
    except ValueError:pass
    else:raise AssertionError('Changed end year was accepted')
validate(2026,schema['properties']['end_year'])
original=data_pipeline.provider
config=configuration('external',{'embedding':'gemini-embedding-2'})
router=StageRouter(config['stage_providers'],{},Path(sys.argv[2]),'test',config,scope)
with router:
    assert data_pipeline.provider()=='google'
assert data_pipeline.provider is original
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(Path(__file__).resolve().parents[1]),
            str(tmp_path),
        ],
        env=_worker_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_no_year_scope_stays_null():
    _, schema = planner_contract("task", {"properties": {}}, "Tài liệu văn hóa Hà Nam")
    assert schema["properties"]["start_year"] == {"type": "null"}


@pytest.mark.parametrize(
    "url",
    [
        "http://vertexaisearch.cloud.google.com/grounding-api-redirect/test",
        "https://vertexaisearch.cloud.google.com/not-a-citation",
        "https://username:password@vertexaisearch.cloud.google.com/grounding-api-redirect/test",
        "http://127.0.0.1/private",
    ],
)
def test_citation_resolution_rejects_unsafe_targets_before_connecting(url):
    with pytest.raises(ValueError):
        resolve_grounding_url(url)
