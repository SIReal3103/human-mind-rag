"""App-owned provider routing around original upstream calls in an isolated worker."""

from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from provider_health import STAGE_LABELS, diagnostic, error_diagnostic

STAGES = ("planner", "search", "check", "embedding", "evidence")


def stage_providers(value=None, default="btc"):
    if default not in ("btc", "openai") or (value is not None and not isinstance(value, dict)):
        raise ValueError("Chọn BTC hoặc OpenAI cho từng bước; không tự chuyển provider.")
    value = value or {}
    if set(value) - set(STAGES):
        raise ValueError("Bước API không được hỗ trợ.")
    result = {stage: value.get(stage, default) for stage in STAGES}
    if any(provider not in ("btc", "openai") for provider in result.values()):
        raise ValueError(
            "Repo gốc chỉ hỗ trợ BTC/OpenAI trong pipeline; Google/Veo hiện chỉ lưu và kiểm tra key."
        )
    return result


def stages_for(action):
    return {
        "crawl": ("planner", "search", "check"),
        "build": ("embedding",),
        "retrieve": ("embedding", "evidence"),
    }[action]


def structured_stage(name):
    if name == "scope-planner":
        return "planner"
    if name == "source-ranking" or name.startswith("document-check-"):
        return "check"
    if name.startswith(("query-scope-", "context-rerank-")):
        return "evidence"
    raise ValueError("Unknown upstream structured API stage")


def read_events(folder):
    path = Path(folder) / "api-events.json"
    try:
        if path.stat().st_size <= 2_000_000:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return data[-500:]
    except (OSError, ValueError):
        pass
    return []


class StageRouter:
    def __init__(self, profiles, credentials, folder, attempt, config=None, scope=""):
        self.profiles = config["stage_providers"] if config else stage_providers(profiles)
        self.models = config["stage_models"] if config else None
        self.scope = scope
        self.gateway = None
        if config:
            from model_gateway import ModelGateway

            self.gateway = ModelGateway(self.profiles, self.models, credentials)
        self.credentials = credentials
        self.folder = Path(folder)
        self.attempt = attempt
        self.events = read_events(folder)
        self.patches = []

    @contextmanager
    def profile(self, stage):
        provider = self.profiles[stage]
        credential = self.credentials.get(provider)
        if not credential or not credential.get("key"):
            raise ValueError(f"{STAGE_LABELS[stage]}: Chưa lưu key cho {provider}.")
        names = ("AI_PROVIDER", "BTC_API_KEY", "OPENAI_API_KEY", "THUCCHIEN_API_KEY")
        previous = {name: os.environ.get(name) for name in names}
        os.environ.update(
            {
                "AI_PROVIDER": "btc" if provider == "btc" else "openai",
                "BTC_API_KEY": "",
                "OPENAI_API_KEY": "",
                "THUCCHIEN_API_KEY": "",
            }
        )
        os.environ["BTC_API_KEY" if provider == "btc" else "OPENAI_API_KEY"] = credential["key"]
        try:
            yield provider
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def save(self):
        path = self.folder / "api-events.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.events[-500:], ensure_ascii=False))
        temporary.replace(path)

    def call(self, stage, function, *args, **kwargs):
        import gateway

        with self.profile(stage) as provider:
            event = {
                **diagnostic(provider, stage, "ok"),
                "id": uuid4().hex,
                "attempt": self.attempt,
                "credential_version": self.credentials[provider]["version"],
                "state": "running",
                "model": self.models[stage]
                if self.models
                else args[1]
                if stage == "embedding"
                else gateway.text_model(),
            }
            event["status"] = "running"
            self.events.append(event)
            self.save()
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                event.update(error_diagnostic(provider, stage, error), state="failed")
                raise
            else:
                event.update(diagnostic(provider, stage, "ok"), state="success")
                return result
            finally:
                self.save()

    def __enter__(self):
        import gateway

        # The index's provider is a provenance and compatibility field. Original
        # gateway env parsing only knows BTC/OpenAI, so bind this reader explicitly
        # for new external model families without mislabelling Google as OpenAI.
        if self.gateway:
            import data_pipeline

        original_structured = gateway.structured_request
        original_search = gateway.search_gateway

        @wraps(original_structured)
        def structured(task, schema, folder, name):
            stage = structured_stage(name)
            if self.gateway:
                if stage == "planner":
                    from model_catalog import planner_contract

                    task, schema = planner_contract(task, schema, self.scope)
                if name.startswith("document-check-"):
                    from document_check import evidence_segments, evidence_error, correction_task

                    segments = evidence_segments(task)
                    result, evidence = self.call(
                        stage, self.gateway.structured, stage, task, schema, folder, name
                    )
                    issue = evidence_error(result, segments)
                    self.events[-1]["validation"] = "rejected" if issue else "accepted"
                    self.save()
                    if issue:
                        result, evidence = self.call(
                            stage,
                            self.gateway.structured,
                            stage,
                            correction_task(task, result, segments),
                            schema,
                            folder,
                            name + "-repair",
                        )
                        issue = evidence_error(result, segments)
                        self.events[-1]["validation"] = "rejected" if issue else "accepted"
                        self.save()
                        if issue:
                            raise ValueError(issue)
                    return result, evidence
                return self.call(stage, self.gateway.structured, stage, task, schema, folder, name)
            return self.call(stage, original_structured, task, schema, folder, name)

        @wraps(original_search)
        def search(*args, **kwargs):
            return self.call(
                "search", self.gateway.search if self.gateway else original_search, *args, **kwargs
            )

        # App-owned model adapters leave upstream discovery, parsing, semantic
        # validators, approval snapshots and retrieval algorithms intact.
        gateway.structured_request = structured
        gateway.search_gateway = search
        self.patches = [
            (gateway, "structured_request", original_structured),
            (gateway, "search_gateway", original_search),
        ]
        if self.gateway:
            self.patches.append((data_pipeline, "provider", data_pipeline.provider))
            data_pipeline.provider = lambda: self.profiles["embedding"]
        for name in ("semantic", "data_pipeline"):
            module = sys.modules.get(name)
            if module:
                self.patches.append((module, "structured_request", module.structured_request))
                module.structured_request = structured
        self.original_structured = original_structured
        return self

    def __exit__(self, *error):
        for module, name, original in reversed(self.patches):
            setattr(module, name, original)
        # Modules imported while routing was active captured the wrapper.
        for name in ("semantic", "data_pipeline"):
            module = sys.modules.get(name)
            if (
                module
                and getattr(module.structured_request, "__wrapped__", None)
                is self.original_structured
            ):
                module.structured_request = self.original_structured

    def embedding_request(self, texts, model, dimensions):
        from data_pipeline import embedding_request

        return self.call(
            "embedding",
            self.gateway.embedding if self.gateway else embedding_request,
            texts,
            model,
            dimensions,
        )
