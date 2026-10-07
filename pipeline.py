"""Persisted local jobs bridging upstream crawls and human-approved snapshots."""

import hashlib
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread
from uuid import uuid4

from ingestion import _worker_environment, _require_upstream, MAX_BYTES, MAX_TEXT, UPSTREAM_COMMIT
from store import Conflict, now, today, canonical_date
from api_routing import stage_providers, stages_for
from provider_health import STAGE_LABELS, describe
from model_catalog import configuration, normalize_scope

MODELS = {
    "btc": ("text-multilingual-embedding-002", 768),
    "openai": ("text-embedding-3-small", 1536),
}


def fingerprint(documents):
    return sorted(
        (d["id"], d["revision"], hashlib.sha256(d["text"].encode()).hexdigest()) for d in documents
    )


class Pipeline:
    def __init__(self, store, credentials):
        self.store, self.credentials = store, credentials
        self.folder = store.folder / "pipeline"
        self.folder.mkdir(exist_ok=True)
        self.lock = Lock()
        self.busy = False
        for path in self.folder.glob("*/job.json"):
            job = json.loads(path.read_text())
            owner = job.get("owner_pid")
            alive = False
            if type(owner) is int and owner > 0:
                try:
                    os.kill(owner, 0)
                    alive = True
                except PermissionError:
                    alive = True
                except ProcessLookupError:
                    pass
            # Importing a second app instance must not interrupt another live server.
            # Legacy jobs without an owner cannot safely be classified here.
            if job["status"] == "running" and owner is not None and not alive:
                job.update(
                    status="interrupted",
                    error="Server khởi động lại. Tạo phiên mới; tài liệu đã nhập vẫn được giữ.",
                )
                self.save(job)

    def save(self, job):
        folder = self.folder / job["id"]
        folder.mkdir(exist_ok=True)
        path = folder / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False))
        temporary.replace(path)

    def get(self, identifier):
        if (
            not isinstance(identifier, str)
            or len(identifier) != 32
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise ValueError("Mã phiên không hợp lệ.")
        path = self.folder / identifier / "job.json"
        if not path.exists():
            raise KeyError(identifier)
        return json.loads(path.read_text())

    def list(self):
        return sorted(
            (json.loads(p.read_text()) for p in self.folder.glob("*/job.json")),
            key=lambda j: j["created_at"],
            reverse=True,
        )

    def eligible(self, job):
        return self.store.export(job["collection"], job["as_of"])["documents"]

    def assert_current(self, job):
        if job["as_of"] != today() or fingerprint(self.eligible(job)) != [
            tuple(x) for x in job["approved_versions"]
        ]:
            raise Conflict(
                "Index đã cũ do thay đổi tài liệu/hiệu lực. Tạo lại index trước khi lấy evidence."
            )

    def worker(self, request, key=""):
        folder = Path(request["folder"])
        result = folder / ("result-" + uuid4().hex + ".json")
        payload = {**request, "api_attempt": uuid4().hex, "result": str(result)}
        payload.update({"credentials": key} if isinstance(key, dict) else {"key": key})
        try:
            subprocess.run(
                [sys.executable, "-I", str(Path(__file__).with_name("pipeline_worker.py"))],
                input=json.dumps(payload),
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_worker_environment(),
                timeout=1800,
                check=True,
            )
            response = json.loads(result.read_text())
            events = response.get("api_events", [])
            failures = [event for event in events if event.get("state") == "failed"]
            for event in events:
                if event.get("state") in ("success", "failed"):
                    self.credentials.record_check(
                        event["provider"], event["credential_version"], event
                    )
            if not response["ok"]:
                raise ValueError(describe(failures[-1]) if failures else response["error"])
            result_data = response["result"]
            if request["action"] == "crawl" and failures:
                result_data["api_errors"] = [describe(event) for event in failures]
                if result_data.get("error"):
                    result_data["error"] = describe(failures[-1])
            return result_data
        except (subprocess.SubprocessError, OSError):
            raise ValueError(
                "Pipeline hết thời gian hoặc worker dừng. Tạo phiên mới để thử lại."
            ) from None
        finally:
            result.unlink(missing_ok=True)

    def start(self, payload):
        _require_upstream()
        action = payload.get("action")
        collection = payload.get("collection", "")
        scope = payload.get("scope", "")
        if (
            action not in ("crawl", "build")
            or not isinstance(collection, str)
            or not 1 <= len(collection.strip()) <= 100
            or not isinstance(scope, str)
            or not 12 <= len(scope.strip()) <= 8000
        ):
            raise ValueError("Cần tác vụ crawl/build, bộ tài liệu và phạm vi 12–8.000 ký tự.")
        job = {
            "id": uuid4().hex,
            "action": action,
            "collection": collection.strip(),
            "scope": scope.strip(),
            "created_at": now(),
            "owner_pid": os.getpid(),
            "status": "running",
            "document_ids": [],
            "errors": [],
            "integration": "upstream-stage-routing",
            "upstream_commit": UPSTREAM_COMMIT,
        }
        if type(payload.get("auto_approve", False)) is not bool:
            raise ValueError("Chế độ tự động duyệt phải là bật/tắt.")
        job["auto_approve"] = payload.get("auto_approve", False)
        if payload.get("seed_urls"):
            raise ValueError(
                "Pipeline gốc tự tìm nguồn từ phạm vi; không nhận seed_urls. Tải lại trang để dùng biểu mẫu mới."
            )
        config = (
            configuration(payload.get("key_group", "btc"), payload.get("stage_models"))
            if "key_group" in payload or "stage_models" in payload
            else None
        )
        profiles = (
            config["stage_providers"]
            if config
            else stage_providers(payload.get("stage_providers"), payload.get("provider", "btc"))
        )
        if config:
            job.update(config, integration="upstream-model-routing")
            job["effective_scope"] = normalize_scope(job["scope"], today())
            job["scope_resolved_on"] = today()
        provider = profiles["planner" if action == "crawl" else "embedding"]
        job.update(provider=provider, stage_providers=profiles)
        key = self.stage_credentials(profiles, action)
        job["credential_versions"] = {name: value["version"] for name, value in key.items()}
        if action == "crawl":
            job.update(planner="model", search_provider="openai")
            for name, default, high in (
                ("max_sources", 5, 10),
                ("max_pages", 12, 30),
                ("max_depth", 1, 2),
            ):
                value = payload.get(name, default)
                if type(value) is not int or not (0 if name == "max_depth" else 1) <= value <= high:
                    raise ValueError("Giới hạn crawl không hợp lệ.")
                job[name] = value
        else:
            job.update(
                provider=provider,
                model=config["stage_models"]["embedding"] if config else MODELS[provider][0],
                dimensions=config["dimensions"] if config else MODELS[provider][1],
                max_chunks=400,
                as_of=today(),
            )
            canonical_date(job["as_of"])
            docs = self.eligible(job)
            if not docs:
                raise ValueError("Chưa có tài liệu đã duyệt còn hiệu lực trong bộ này.")
            job["approved_versions"] = fingerprint(docs)
        with self.lock:
            if self.busy:
                raise Conflict("Một tác vụ pipeline đang chạy. Đợi hoàn tất rồi thử lại.")
            self.busy = True
            try:
                self.save(job)
                if action == "build":
                    originals = self.folder / job["id"] / "originals"
                    originals.mkdir()
                    for doc in docs:
                        raw = (self.store.raw / doc["id"]).read_bytes()
                        if hashlib.sha256(raw).hexdigest() != doc["source_sha256"]:
                            raise ValueError("Bản gốc thay đổi; dừng xuất index.")
                        (originals / doc["id"]).write_bytes(raw)
                    (self.folder / job["id"] / "approved.json").write_text(
                        json.dumps({"documents": docs}, ensure_ascii=False)
                    )
                Thread(target=self.run, args=(job, key), daemon=True).start()
            except BaseException:
                job.update(
                    status="failed",
                    error="Không tạo được snapshot; kiểm tra bản gốc và dung lượng lưu trữ.",
                )
                self.save(job)
                self.busy = False
                raise
        return job

    def stage_credentials(self, profiles, action):
        selected = {}
        for stage in stages_for(action):
            provider = profiles[stage]
            if provider not in selected:
                try:
                    selected[provider] = self.credentials.snapshot(provider)
                except ValueError as error:
                    raise ValueError(f"{STAGE_LABELS[stage]} · {provider}: {error}") from None
        return selected

    def import_run(self, job, run):
        run = Path(run).resolve()
        if not run.is_relative_to((self.folder / job["id"] / "crawl").resolve()):
            raise ValueError("Thư mục crawl ngoài phiên.")
        report = json.loads((run / "report.json").read_text())
        fetch_path = run / "fetch-manifest.json"
        fetches = json.loads(fetch_path.read_text()) if fetch_path.exists() else []
        entries = list(report.get("documents", []))
        entries.extend(
            {"parsed_path": str(p.relative_to(run))}
            for p in sorted((run / "parsed").glob("series-*.json"))
        )
        existing = [self.store.get(identifier) for identifier in job["document_ids"]]
        imported_paths = {d.get("crawl", {}).get("parsed_path") for d in existing}
        imported_hashes = {d["source_sha256"] for d in existing}
        for entry in entries:
            relative = entry.get("parsed_path") or entry.get("unassessed_path")
            if (relative and relative in imported_paths) or (
                not relative and not entry.get("raw_path")
            ):
                continue
            try:
                if relative:
                    path = (run / relative).resolve()
                    if not path.is_relative_to(run) or path.stat().st_size > 20_000_000:
                        raise ValueError("Parsed artifact không hợp lệ")
                    parsed = json.loads(path.read_text())
                else:
                    record = next(
                        r
                        for r in fetches
                        if r.get("raw_path") == entry["raw_path"] and r.get("status") == "success"
                    )
                    parsed = {
                        "text": "",
                        "parser": "extraction-failed",
                        "raw_path": record["raw_path"],
                        "raw_sha256": record["sha256"],
                        "url": record.get("final_url", entry.get("url")),
                        "status": "failed",
                        "parse_warnings": [
                            "Không trích được nội dung; đối chiếu bản gốc và bổ sung văn bản trước khi duyệt."
                        ],
                    }
                rows = parsed.get("rows") or []
                if rows and not parsed.get("raw_path"):
                    parsed["raw_path"] = rows[0]["raw_path"]
                    parsed["raw_sha256"] = rows[0]["raw_sha256"]
                    parsed["title"] = parsed.get("indicator", {}).get("name", "Bảng số liệu")
                raw = (run / parsed["raw_path"]).resolve()
                if not raw.is_relative_to(run) or raw.stat().st_size > MAX_BYTES:
                    raise ValueError("Raw artifact không hợp lệ")
                body = raw.read_bytes()
                if hashlib.sha256(body).hexdigest() != parsed["raw_sha256"]:
                    raise ValueError("Source hash mismatch")
                if not relative and parsed["raw_sha256"] in imported_hashes:
                    continue
                warnings = [str(w) for w in parsed.get("parse_warnings", [])]
                if entry.get("status") == "out_of_scope":
                    warnings.append(
                        "AI đánh giá tài liệu ngoài hoặc thiếu phạm vi yêu cầu. Người duyệt cần quyết định mức phù hợp; chưa đưa vào RAG."
                    )
                text = parsed.get("text") or (json.dumps(rows, ensure_ascii=False) if rows else "")
                if len(text) > MAX_TEXT:
                    raise ValueError("Text quá lớn")
                if parsed.get("tables") and not parsed.get("pages"):
                    text += "\n\nBảng trích xuất (cần đối chiếu bản gốc):\n" + json.dumps(
                        parsed["tables"], ensure_ascii=False
                    )
                if len(text) > MAX_TEXT:
                    raise ValueError("Text và bảng quá lớn")
                segments = [
                    {"text": p["text"], "locator": {"kind": "page", "page": p["page"]}}
                    for p in parsed.get("pages", [])
                    if p.get("text")
                ]
                if text and not segments:
                    segments = [{"text": text, "locator": {"kind": "document_text"}}]
                doc = self.store.create(
                    body,
                    {
                        "text": text,
                        "parser": parsed.get("parser", "scope-data-bot"),
                        "segments": segments,
                        "warnings": warnings,
                        "partial": parsed.get("parse_partial", False),
                    },
                    {
                        "title": str(parsed.get("title") or entry.get("title") or "Tài liệu crawl")[
                            :300
                        ],
                        "collection": job["collection"],
                        "source_id": "url-"
                        + hashlib.sha256(str(parsed.get("url", "")).encode()).hexdigest()[:24],
                        "document_version": job["id"],
                    },
                    source_kind="web",
                    filename=raw.name,
                    mime="application/pdf"
                    if body.startswith(b"%PDF-")
                    else (mimetypes.guess_type(raw.name)[0] or "text/plain"),
                    source_url=parsed.get("url"),
                    crawl={
                        "job_id": job["id"],
                        "upstream_status": parsed.get("status"),
                        "assessment": parsed.get("assessment"),
                        "scope_reason": entry.get("reason", "")
                        if entry.get("status") == "out_of_scope"
                        else "",
                        "parsed_path": relative,
                    },
                )
                job["document_ids"].append(doc["id"])
                imported_paths.add(relative)
                imported_hashes.add(parsed["raw_sha256"])
            except (ValueError, KeyError, OSError, TypeError, StopIteration):
                job["errors"].append(
                    "Không nhập được một tài liệu: kiểm tra cấu trúc, kích thước hoặc hash nguồn."
                )
            self.save(job)
        from pipeline_worker import safe_error

        job["crawl_summary"] = (
            safe_error(ValueError(report["error"]))
            if report.get("error")
            else report.get("summary", "")
        )
        job["crawl_counts"] = report.get("counts", {})

    def auto_review(self, identifier):
        with self.lock:
            if self.busy:
                raise Conflict("Đợi tác vụ đang chạy hoàn tất trước khi tự duyệt.")
            job = self.get(identifier)
            if job["action"] != "crawl" or job["status"] == "running":
                raise Conflict("Chỉ tự duyệt tài liệu của phiên crawl đã kết thúc.")
            self.apply_auto_review(job)
            self.save(job)
            return job

    def apply_auto_review(self, job):
        from auto_review import blockers, ACTOR, POLICY, approval_mode

        outcomes = []
        for identifier in job["document_ids"]:
            doc = self.store.get(identifier)
            if doc["status"] != "pending":
                outcomes.append(
                    {
                        "id": identifier,
                        "status": doc["status"],
                        "reasons": [],
                        "approval_mode": approval_mode(doc),
                        "newly_approved": False,
                    }
                )
                continue
            reasons = blockers(doc)
            if not reasons:
                try:
                    self.store.decide(
                        identifier,
                        {
                            "action": "approve",
                            "revision": doc["revision"],
                            "actor": ACTOR,
                            "approval_mode": "automatic",
                            "note": "Tự động duyệt theo "
                            + POLICY
                            + ": đạt kiểm tra cấu trúc và phạm vi AI; chưa xác minh sự thật độc lập.",
                        },
                    )
                except (ValueError, Conflict) as error:
                    reasons = [str(error)]
            outcomes.append(
                {
                    "id": identifier,
                    "status": "pending" if reasons else "approved",
                    "approval_mode": None if reasons else "automatic",
                    "newly_approved": not reasons,
                    "reasons": reasons,
                }
            )
        job["auto_review"] = {"policy": POLICY, "at": now(), "outcomes": outcomes}

    def run(self, job, key):
        try:
            result = self.worker({**job, "folder": str(self.folder / job["id"])}, key)
            if job["action"] == "crawl":
                self.import_run(job, result["run"])
                job["status"] = (
                    "needs_review"
                    if job["document_ids"]
                    else "failed"
                    if result.get("error") or result.get("api_errors")
                    else "no_documents"
                )
                if result.get("error"):
                    job["error"] = result["error"]
                job["errors"].extend(result.get("api_errors", []))
                if job.get("auto_approve"):
                    self.apply_auto_review(job)
            else:
                self.assert_current(job)
                job["manifest"] = result
                job["status"] = "ready"
        except Exception as error:
            job.update(
                status="failed",
                error=str(error)
                if isinstance(error, (ValueError, Conflict))
                else "Lỗi pipeline nội bộ.",
            )
        finally:
            job["finished_at"] = now()
            self.save(job)
            with self.lock:
                self.busy = False

    def evidence(self, identifier, question, evidence_provider=None, evidence_model=None):
        job = self.get(identifier)
        if job["action"] != "build" or job["status"] != "ready":
            raise Conflict("Index chưa sẵn sàng.")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 8000:
            raise ValueError("Câu hỏi cần 1–8.000 ký tự.")
        self.assert_current(job)
        config = (
            configuration(
                job["key_group"],
                {
                    **job["stage_models"],
                    **({"evidence": evidence_model} if evidence_model is not None else {}),
                },
            )
            if job.get("key_group")
            else None
        )
        profiles = (
            config["stage_providers"]
            if config
            else stage_providers(job.get("stage_providers"), job["provider"])
        )
        # Query vectors must use exactly the provider/model of the indexed corpus.
        profiles["embedding"] = job["provider"]
        if evidence_provider is not None and not config:
            profiles["evidence"] = evidence_provider
        if not config:
            profiles = stage_providers(profiles)
        result = self.worker(
            {
                **job,
                **(config or {}),
                "action": "retrieve",
                "stage_providers": profiles,
                "question": question,
                "folder": str(self.folder / identifier),
            },
            self.stage_credentials(profiles, "retrieve"),
        )
        self.assert_current(job)
        path = self.folder / identifier / "last-evidence.json"
        temporary = path.with_name("last-evidence-" + uuid4().hex + ".tmp")
        temporary.write_text(
            json.dumps(
                {"question": question, "created_at": now(), "bundle": result}, ensure_ascii=False
            )
        )
        temporary.replace(path)
        return result

    def last_evidence(self, identifier):
        job = self.get(identifier)
        if job["action"] != "build" or job["status"] != "ready":
            raise Conflict("Index chưa sẵn sàng.")
        # Saved context has the same withdrawal/expiry gate as a new query.
        self.assert_current(job)
        path = self.folder / identifier / "last-evidence.json"
        result = json.loads(path.read_text()) if path.exists() else None
        self.assert_current(job)
        return result
