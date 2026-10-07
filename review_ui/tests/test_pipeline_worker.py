"""Provider diagnostics and transport configuration without paid calls."""

from pathlib import Path
import subprocess
import sys

import pytest

from ingestion import _worker_environment
from pipeline_worker import safe_error


@pytest.mark.parametrize("code", ["401", "403", "429", "503"])
def test_provider_status_is_actionable_without_echoing_bodies(code):
    result = safe_error(ValueError(f"AI_HTTP_{code}: request failed; provider body omitted"))
    assert f"AI_HTTP_{code}" in result
    assert "Kiểm tra" in result


def test_unknown_provider_messages_are_not_persisted():
    secret = "private-request-body-and-key"
    for value in [secret, "AI_HTTP_401: " + secret, "AI_NETWORK_ERROR: " + secret]:
        assert secret not in safe_error(ValueError(value))
    assert "HTTPS" in safe_error(ValueError("AI_NETWORK_ERROR: request failed"))


def test_discovery_blocker_is_visible_without_echoing_untrusted_details():
    message = "Không thể tìm nguồn: mọi truy vấn đã thất bại. Search bị CAPTCHA private-key"
    result = safe_error(ValueError(message))
    assert "CAPTCHA" in result
    assert "private-key" not in result


def test_native_crawl_keeps_upstream_functions_and_capability_gate(tmp_path):
    program = """import json,sys,ssl,urllib.request
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ingestion import _require_upstream
info=_require_upstream()
assert info['integration']=='bundled'
sys.path.insert(0,info['path'])
import bot,ai_http,data_pipeline
originals=(bot.discover,bot.PublicHTTP.__init__,ai_http.AI_OPENER,data_pipeline.embedding_request)
from pipeline_worker import execute
result=execute({'action':'crawl','provider':'btc','scope':'Kinh tế Hà Nam giai đoạn 2020–2024','folder':sys.argv[2],'max_sources':1,'max_pages':1,'max_depth':0})
assert 'BTC_STRUCTURED_VERIFIED' in result['error'], result
assert originals==(bot.discover,bot.PublicHTTP.__init__,ai_http.AI_OPENER,data_pipeline.embedding_request)
report=json.loads((Path(result['run'])/'report.json').read_text())
assert report['documents']==[] and report['candidates']==[]
lineage=json.loads((Path(result['run'])/'lineage.json').read_text())
assert any(n['label']=='Planner hiểu yêu cầu' and n['status']=='failed' for n in lineage['nodes'])
assert not list(Path(sys.argv[2]).rglob('index.sqlite'))
context=ssl.create_default_context()
assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
assert context.get_ca_certs()
redirect=next(h for h in ai_http.AI_OPENER.handlers if isinstance(h,ai_http.NoAIRedirect))
try: redirect.redirect_request(None,None,302,'',{},'https://example.com/')
except ValueError: pass
else: raise AssertionError('AI redirects must remain blocked')
try: ai_http.post('https://example.com/embeddings',{},'test-only')
except ValueError as e: assert 'allowlist' in str(e)
else: raise AssertionError('Destination must remain restricted')
"""
    environment = _worker_environment()
    for flag in (
        "BTC_STRUCTURED_VERIFIED",
        "BTC_SEARCH_VERIFIED",
        "BTC_EMBEDDING_VERIFIED",
        "BTC_EMBEDDING_BATCH_VERIFIED",
    ):
        environment[flag] = "0"
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
        env=environment,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr


def test_native_capability_error_is_actionable_and_strictly_sanitized():
    error = "CAPABILITY_UNVERIFIED: BTC_SEARCH_VERIFIED; smoke-test BTC before enabling"
    assert "BTC_SEARCH_VERIFIED" in safe_error(ValueError(error))
    assert "private-body" not in safe_error(ValueError(error + " private-body"))
