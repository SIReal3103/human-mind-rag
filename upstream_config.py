"""Read-only view of the pinned upstream gateway's own settings; no API adapter."""

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingestion import _require_upstream, _worker_environment

# Forward only settings understood by upstream, without filling defaults here.
SETTING_NAMES = (
    "AI_PROVIDER",
    "OPENAI_API_KEY",
    "THUCCHIEN_API_KEY",
    "BTC_API_KEY",
    "OPENAI_SEARCH_MODEL",
    "BTC_TEXT_MODEL",
    "OPENAI_EMBEDDING_MODEL",
    "BTC_EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "BTC_STRUCTURED_VERIFIED",
    "BTC_SEARCH_VERIFIED",
    "BTC_EMBEDDING_VERIFIED",
    "BTC_EMBEDDING_BATCH_VERIFIED",
    "DOCUMENT_PARSER",
    "DOCUMENT_OCR",
    "DOCUMENT_OCR_LANGUAGES",
    "DOCUMENT_MAX_PAGES",
    "DOCUMENT_TIMEOUT",
    "DOCUMENT_THREADS",
    "DOCLING_PYTHON",
)
GATES = (
    "BTC_STRUCTURED_VERIFIED",
    "BTC_SEARCH_VERIFIED",
    "BTC_EMBEDDING_VERIFIED",
    "BTC_EMBEDDING_BATCH_VERIFIED",
)


def native_environment():
    env = _worker_environment()
    for name in SETTING_NAMES:
        env.pop(name, None)
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def current_config():
    """Run only inside an isolated worker using the native environment."""
    sys.path.insert(0, _require_upstream()["path"])
    import gateway

    provider = gateway.provider()
    text = gateway.text_model()
    embedding = gateway.setting(
        "BTC_EMBEDDING_MODEL" if provider == "btc" else "OPENAI_EMBEDDING_MODEL",
        "text-multilingual-embedding-002" if provider == "btc" else "text-embedding-3-small",
    )
    dimensions = int(
        gateway.setting("EMBEDDING_DIMENSIONS", "768" if provider == "btc" else "1536")
    )
    if not 1 <= dimensions <= 3072:
        raise ValueError("Invalid upstream embedding dimensions")
    # Configuration mistakes must not echo arbitrary strings as model names.
    import re

    if any(
        not isinstance(v, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", v)
        or v.startswith(("sk-", "AIza", "ghp_"))
        for v in (text, embedding)
    ):
        raise ValueError("Invalid upstream model configuration")
    key_names = ("BTC_API_KEY",) if provider == "btc" else ("OPENAI_API_KEY", "THUCCHIEN_API_KEY")
    key_name = next((name for name in key_names if gateway.setting(name)), key_names[0])
    return {
        "mode": "upstream-native-api",
        "provider": provider,
        "text_model": text,
        "embedding_model": embedding,
        "dimensions": dimensions,
        "endpoints": {
            "text_search": gateway.endpoint("responses"),
            "embedding": gateway.endpoint("embeddings"),
        },
        "capabilities": {name: gateway.setting(name) == "1" for name in GATES},
        "key": {
            "name": key_name,
            "configured": bool(gateway.gateway_key()),
            "source": "environment" if key_name in os.environ else "upstream .env.local",
        },
        "precedence": "environment > scope-data-bot/.env.local > upstream defaults",
    }


def freeze_config(expected=None):
    """Pin the effective native profile for one worker, never alter upstream functions."""
    sys.path.insert(0, _require_upstream()["path"])
    import gateway

    path = Path(gateway.__file__).with_name(".env.local")

    def signature():
        import hashlib

        return hashlib.sha256(path.read_bytes()).digest() if path.exists() else None

    for _ in range(3):
        before = signature()
        config = current_config()
        keys = {
            name: gateway.setting(name, "")
            for name in ("OPENAI_API_KEY", "THUCCHIEN_API_KEY", "BTC_API_KEY")
        }
        if before == signature():
            break
    else:
        raise ValueError("UPSTREAM_CONFIG_CHANGED")
    if expected and routing_signature(config) != routing_signature(expected):
        raise ValueError("UPSTREAM_CONFIG_CHANGED")
    provider = config["provider"]
    os.environ.update(
        {
            **keys,
            "AI_PROVIDER": provider,
            "BTC_TEXT_MODEL" if provider == "btc" else "OPENAI_SEARCH_MODEL": config["text_model"],
            "BTC_EMBEDDING_MODEL" if provider == "btc" else "OPENAI_EMBEDDING_MODEL": config[
                "embedding_model"
            ],
            "EMBEDDING_DIMENSIONS": str(config["dimensions"]),
            **{name: "1" if enabled else "0" for name, enabled in config["capabilities"].items()},
        }
    )
    return config


def read_config():
    _require_upstream()
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve())],
            env=native_environment(),
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError):
        raise ValueError(
            "Không đọc được cấu hình API upstream. Kiểm tra AI_PROVIDER, model và EMBEDDING_DIMENSIONS trong environment hoặc scope-data-bot/.env.local."
        ) from None


def routing_signature(config):
    return {
        name: config[name]
        for name in (
            "provider",
            "text_model",
            "embedding_model",
            "dimensions",
            "endpoints",
            "capabilities",
        )
    }


if __name__ == "__main__":
    print(json.dumps(current_config()))
