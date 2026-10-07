"""Bounded local Docling adapter. Only downloaded bytes cross the worker boundary.

Run ./setup-parser.sh once for local layout/table/OCR models. No AI key is needed.
DOCUMENT_PARSER=auto uses Docling when installed; native explicitly selects pypdf.
Cache stores parser output, never an assessment: every scope is checked separately.
"""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from urllib.parse import urlsplit

from engine import ValidationError, save_json
from gateway import setting

ROOT = Path(__file__).resolve().parent
FORMATS = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/tiff": "tiff",
    "image/webp": "webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


def document_type(content_type, url, body):
    if body.startswith(b"%PDF-"):
        return "application/pdf"
    if content_type in ("application/octet-stream", "text/plain"):
        extension = Path(urlsplit(url).path).suffix.lower().removeprefix(".")
        if extension == "jpeg":
            extension = "jpg"
        return next((mime for mime, suffix in FORMATS.items() if suffix == extension), content_type)
    return content_type


def parser_options():
    def number(name, default, minimum, maximum):
        try:
            value = int(setting(name, str(default)))
        except ValueError:
            raise ValidationError(f"{name} must be an integer") from None
        if not minimum <= value <= maximum:
            raise ValidationError(f"{name} must be {minimum}–{maximum}")
        return value

    mode = setting("DOCUMENT_PARSER", "auto")
    if mode not in ("auto", "docling", "native"):
        raise ValidationError("DOCUMENT_PARSER must be auto, docling or native")
    ocr = setting("DOCUMENT_OCR", "auto")
    if ocr not in ("auto", "full", "off"):
        raise ValidationError("DOCUMENT_OCR must be auto, full or off")
    languages = setting("DOCUMENT_OCR_LANGUAGES", "vi,en").split(",")
    if languages not in (["vi", "en"], ["en"], ["vi"]):
        raise ValidationError("DOCUMENT_OCR_LANGUAGES must be vi,en, vi or en")
    return {
        "mode": mode,
        "ocr": ocr,
        "languages": languages,
        "max_pages": number("DOCUMENT_MAX_PAGES", 40, 1, 200),
        "timeout": number("DOCUMENT_TIMEOUT", 180, 10, 600),
        "threads": number("DOCUMENT_THREADS", 2, 1, 8),
        "models_sha256": hashlib.sha256((ROOT / ".parser-models.json").read_bytes()).hexdigest()
        if (ROOT / ".parser-models.json").exists()
        else None,
    }


def runtime():
    return Path(setting("DOCLING_PYTHON", str(ROOT / ".venv-docling/bin/python"))).expanduser()


def should_use_docling(content_type, body):
    if content_type not in FORMATS and not body.startswith(b"%PDF-"):
        return False
    mode = parser_options()["mode"]
    if mode == "native":
        return False
    if mode == "docling" or runtime().is_file():
        return True
    if content_type != "application/pdf" and not body.startswith(b"%PDF-"):
        raise ValidationError("DOCLING_NOT_INSTALLED: run ./setup-parser.sh for images/Office")
    return False


def worker_environment():
    # Do not pass parent API keys, proxy settings or arbitrary Python paths to OCR.
    allowed = ("PATH", "HOME", "TMPDIR", "SYSTEMROOT", "LANG", "LC_ALL")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    return env


def run_worker(command, timeout):
    process = subprocess.Popen(
        command,
        env=worker_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        code = process.wait(timeout=timeout)
    except BaseException:
        # Kill descendants too; a timed-out OCR subprocess must not keep consuming CPU.
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait()
        raise
    if code:
        raise ValidationError(
            f"DOCLING_WORKER_FAILED: exit {code}; run ./setup-parser.sh and check models"
        )


def validate_output(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("text"), str) or not doc["text"].strip():
        raise ValidationError("DOCLING_EMPTY_OUTPUT: no text/OCR evidence extracted")
    if len(doc["text"]) > 600_000 or not isinstance(doc.get("pages"), list):
        raise ValidationError("DOCLING_OUTPUT_LIMIT: text/pages contract")
    if doc.get("parser") != "docling-local-v1" or not isinstance(doc.get("parser_config"), dict):
        raise ValidationError("DOCLING_OUTPUT_CONTRACT: missing parser/config")
    return doc


def parse_document(body, content_type, cache_dir=None):
    if len(body) > 10_000_000:
        raise ValidationError("DOCLING_INPUT_LIMIT: maximum 10 MB")
    options = parser_options()
    python = runtime()
    if not python.is_file():
        raise ValidationError("DOCLING_NOT_INSTALLED: run ./setup-parser.sh")
    extension = "pdf" if body.startswith(b"%PDF-") else FORMATS.get(content_type)
    if extension is None:
        raise ValidationError("DOCLING_FORMAT_UNSUPPORTED")
    worker = ROOT / "docling_worker.py"
    # Runtime lock and adapter source are part of the cache contract.
    signature = hashlib.sha256(
        worker.read_bytes() + (ROOT / "requirements-parser.lock.txt").read_bytes()
    ).hexdigest()
    key = hashlib.sha256(
        body + json.dumps([options, signature], sort_keys=True).encode()
    ).hexdigest()
    cache = Path(cache_dir) / (key + ".json") if cache_dir else None
    if cache and cache.exists():
        if cache.stat().st_size > 20_000_000:
            raise ValidationError("DOCLING_CACHE_LIMIT")
        record = json.loads(cache.read_text(encoding="utf-8"))
        doc = record["document"]
        if (
            record.get("sha256")
            != hashlib.sha256(
                json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        ):
            raise ValidationError("DOCLING_CACHE_INTEGRITY")
        return {**validate_output(doc), "parser_cache_hit": True}
    with tempfile.TemporaryDirectory(prefix="scope-parser-") as temp:
        directory = Path(temp)
        source, result, config = (
            directory / ("input." + extension),
            directory / "result.json",
            directory / "config.json",
        )
        source.write_bytes(body)
        save_json(config, options)
        try:
            run_worker(
                [str(python), str(worker), str(source), str(result), str(config)],
                options["timeout"],
            )
        except subprocess.TimeoutExpired:
            raise ValidationError(
                f"DOCLING_TIMEOUT: exceeded {options['timeout']} seconds"
            ) from None
        if not result.exists() or result.stat().st_size > 20_000_000:
            raise ValidationError("DOCLING_OUTPUT_LIMIT: missing/oversized result")
        doc = json.loads(result.read_text(encoding="utf-8"))
        if "error" in doc:
            raise ValidationError(doc["error"])
        validate_output(doc)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        save_json(
            cache,
            {
                "document": doc,
                "sha256": hashlib.sha256(
                    json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
            },
        )
    return {**doc, "parser_cache_hit": False}
