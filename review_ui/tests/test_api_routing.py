"""Exercise native gateway validation/gates with distinct routing; never make paid calls."""

from pathlib import Path
import subprocess
import sys

import pytest

from api_routing import stage_providers, stages_for
from ingestion import _worker_environment


def test_profiles_validate_stages_and_only_require_keys_for_active_action():
    profiles = stage_providers({"planner": "openai", "search": "btc"})
    assert profiles["planner"] == "openai" and profiles["embedding"] == "btc"
    assert stages_for("crawl") == ("planner", "search", "check")
    assert stages_for("build") == ("embedding",)
    assert stages_for("retrieve") == ("embedding", "evidence")
    for invalid in ({"search": "google"}, {"unknown": "openai"}, [], "openai"):
        with pytest.raises(ValueError):
            stage_providers(invalid)


def test_native_gateway_stage_routing_and_restoration(tmp_path):
    program = """import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ingestion import _require_upstream
sys.path.insert(0,_require_upstream()['path'])
from api_routing import StageRouter,read_events
import gateway,ai_http,bot,data_pipeline,semantic
original=(gateway.structured_request,gateway.search_gateway,semantic.structured_request,data_pipeline.structured_request,bot.discover,bot.PublicHTTP.__init__,ai_http.AI_OPENER,data_pipeline.embedding_request)
profiles={'planner':'btc','search':'btc','check':'openai','embedding':'btc','evidence':'openai'}
credentials={p:{'key':'test-'+p+'-not-sent','version':p+'-version'} for p in ('btc','openai')}
before={k:os.environ.get(k) for k in ('AI_PROVIDER','BTC_API_KEY','OPENAI_API_KEY')}
folder=Path(sys.argv[2]);(folder/'raw').mkdir()
router=StageRouter(profiles,credentials,folder,'test-attempt')
with router:
    with router.profile('embedding'):
        assert os.environ['AI_PROVIDER']=='btc'
        # Artifact-name validation and closed BTC gates fail before HTTP.
        calls=[lambda:gateway.structured_request('test',{},folder/'raw','scope-planner'),lambda:gateway.search_gateway('test',folder/'raw',1),lambda:semantic.structured_request('test',{},folder/'raw','document-check-/invalid'),lambda:router.embedding_request(['test'],'text-multilingual-embedding-002',768),lambda:data_pipeline.structured_request('test',{},folder/'raw','query-scope-/invalid')]
        for call in calls:
            try:call()
            except ValueError:pass
            else:raise AssertionError('Expected native validation/gate failure without HTTP')
            assert os.environ['AI_PROVIDER']=='btc'
assert before=={k:os.environ.get(k) for k in before}
assert original==(gateway.structured_request,gateway.search_gateway,semantic.structured_request,data_pipeline.structured_request,bot.discover,bot.PublicHTTP.__init__,ai_http.AI_OPENER,data_pipeline.embedding_request)
events=read_events(folder)
assert [(e['stage'],e['provider']) for e in events]==list(profiles.items())
assert all(e['state']=='failed' for e in events)
assert 'test-openai-not-sent' not in json.dumps(events) and 'test-btc-not-sent' not in json.dumps(events)
assert events[0]['code']=='BTC_STRUCTURED_VERIFIED'
assert events[1]['code']=='BTC_SEARCH_VERIFIED'
assert events[3]['code']=='BTC_EMBEDDING_VERIFIED'
"""
    env = _worker_environment()
    for name in (
        "BTC_STRUCTURED_VERIFIED",
        "BTC_SEARCH_VERIFIED",
        "BTC_EMBEDDING_VERIFIED",
        "BTC_EMBEDDING_BATCH_VERIFIED",
    ):
        env[name] = "0"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(Path(__file__).resolve().parents[1]),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
