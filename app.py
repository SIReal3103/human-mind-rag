"""Local human review API; explicit pipeline builds can call the selected embedding provider."""

import json
import hashlib
import os
import secrets
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from ingestion import extract, fetch_public, upstream_info
from credentials import CredentialStore
from store import Conflict, Store
from pipeline import Pipeline
from model_catalog import catalog
from pipeline_trace import trace_view

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 10_000_000


def parse_for_review(body, mime, filename):
    try:
        return extract(body, mime, filename)
    except ValueError as error:
        if not body.startswith(b"%PDF-") or not upstream_info()["available"]:
            raise
        # Keep unreadable PDFs in staging so the reviewer can inspect the real source.
        return {
            "text": "",
            "parser": "pdf-extraction-failed",
            "segments": [],
            "warnings": [str(error)],
            "partial": False,
        }


def create_app(data_dir=None):
    app = FastAPI(title="Human Mind — Duyệt tài liệu RAG", docs_url=None, redoc_url=None)
    # Keep SQLite on the user's native filesystem: exFAT can change file identity during writes.
    workspace_id = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    default_data = Path.home() / ".local/share/delta-mind-rag-review" / workspace_id
    store = Store(data_dir or os.environ.get("RAG_REVIEW_DATA", str(default_data)))
    csrf_token = secrets.token_urlsafe(32)
    app.state.store = store
    credentials = CredentialStore(store.folder)
    pipeline = Pipeline(store, credentials)
    app.state.pipeline = pipeline

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request, exc):
        # Validation errors may otherwise echo submitted API keys via the input field.
        return JSONResponse(
            {"detail": "Dữ liệu yêu cầu không hợp lệ. Kiểm tra các trường nhập."}, status_code=422
        )

    @app.middleware("http")
    async def protect_local_session(request: Request, call_next):
        host = request.url.hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            return JSONResponse({"detail": "Ứng dụng chỉ phục vụ trên loopback."}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
                return JSONResponse({"detail": "Origin không được phép."}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token):
                return JSONResponse(
                    {"detail": "Phiên làm việc đã đổi. Tải lại trang."}, status_code=403
                )
            length = request.headers.get("content-length", "")
            if not length.isdigit():
                return JSONResponse({"detail": "Request cần Content-Length."}, status_code=411)
            if int(length) > MAX_BYTES + 1_000_000:
                return JSONResponse(
                    {"detail": "Request vượt giới hạn 10 MB cho tài liệu."}, status_code=413
                )
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'",
            }
        )
        return response

    @app.exception_handler(Conflict)
    async def conflict_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing_error(request, exc):
        return JSONResponse({"detail": "Không tìm thấy tài liệu."}, status_code=404)

    @app.get("/api/config")
    def config():
        return {
            "csrf_token": csrf_token,
            "upstream": upstream_info(),
            "limits": {"upload_bytes": MAX_BYTES},
            "retrieval_mode": "fts5",
            "mode": "local-single-reviewer",
        }

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local-single-reviewer"}

    @app.get("/api/credentials")
    def credential_summary():
        return credentials.summary()

    @app.get("/api/models")
    def model_catalog():
        return catalog()

    @app.post("/api/credentials/reset")
    def reset_credentials(payload: dict):
        if set(payload) != {"confirm"} or payload["confirm"] is not True:
            raise ValueError("Cần xác nhận xóa tất cả key đã lưu.")
        return credentials.reset()

    @app.put("/api/credentials/{provider}")
    def save_credential(provider: str, payload: dict):
        if set(payload) != {"api_key"}:
            raise ValueError("Chỉ chấp nhận trường api_key.")
        return credentials.put(provider, payload["api_key"])

    @app.post("/api/credentials/{provider}/check")
    def check_credential(provider: str):
        return credentials.check(provider)

    @app.delete("/api/credentials/{provider}")
    def remove_credential(provider: str):
        return credentials.remove(provider)

    @app.get("/api/pipeline")
    def pipeline_jobs():
        return {"jobs": pipeline.list()}

    @app.get("/api/pipeline/{identifier}/trace")
    def pipeline_trace(identifier: str):
        return trace_view(pipeline, identifier)

    @app.post("/api/pipeline", status_code=202)
    def start_pipeline(payload: dict):
        return pipeline.start(payload)

    @app.post("/api/pipeline/{identifier}/auto-review")
    def auto_review_pipeline(identifier: str):
        return pipeline.auto_review(identifier)

    @app.post("/api/pipeline/{identifier}/evidence")
    def pipeline_evidence(identifier: str, payload: dict):
        return pipeline.evidence(
            identifier, payload.get("question"), payload.get("provider"), payload.get("model")
        )

    @app.get("/api/pipeline/{identifier}/evidence/download")
    def download_pipeline_evidence(identifier: str):
        saved = pipeline.last_evidence(identifier)
        if not saved:
            raise ValueError("Chưa có evidence để tải. Bấm Lấy evidence trước.")
        return JSONResponse(
            saved["bundle"],
            headers={"Content-Disposition": 'attachment; filename="human-mind-evidence.json"'},
        )

    @app.get("/api/pipeline/{identifier}/evidence")
    def last_pipeline_evidence(identifier: str):
        return {"last_evidence": pipeline.last_evidence(identifier)}

    @app.get("/api/documents")
    def documents(status: str | None = None):
        return {"documents": store.list(status)}

    @app.get("/api/documents/{document_id}")
    def document(document_id: str):
        return store.get(document_id)

    @app.post("/api/documents/text", status_code=201)
    def import_text(payload: dict):
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Nhập nội dung văn bản.")
        if len(text) > 600_000 or len(text.encode()) > MAX_BYTES:
            raise ValueError("Văn bản vượt giới hạn 600.000 ký tự.")
        body = text.encode("utf-8")
        parsed = extract(body, "text/plain", "text.txt")
        return store.create(
            body, parsed, payload, source_kind="text", filename="text.txt", mime="text/plain"
        )

    @app.post("/api/documents/upload", status_code=201)
    async def import_upload(
        file: Annotated[UploadFile, File()], metadata: Annotated[str, Form()] = "{}"
    ):
        try:
            values = json.loads(metadata)
        except json.JSONDecodeError:
            raise ValueError("Metadata JSON không hợp lệ.") from None
        if not isinstance(values, dict):
            raise ValueError("Metadata phải là object.")
        filename = Path((file.filename or "document").replace("\\", "/")).name[:240]
        suffix = Path(filename).suffix.lower()
        allowed = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".html": "text/html",
            ".htm": "text/html",
        }
        if suffix not in allowed:
            raise ValueError("Chỉ nhận PDF, TXT, MD và HTML trong bản này.")
        body = await file.read(MAX_BYTES + 1)
        await file.close()
        if not body or len(body) > MAX_BYTES:
            raise ValueError("File rỗng hoặc vượt giới hạn 10 MB.")
        mime = allowed[suffix]
        if (mime == "application/pdf") != body.startswith(b"%PDF-"):
            raise ValueError("Định dạng thực của file không khớp phần mở rộng.")
        values["title"] = values.get("title") or filename
        parsed = await run_in_threadpool(parse_for_review, body, mime, filename)
        return await run_in_threadpool(
            store.create, body, parsed, values, source_kind="file", filename=filename, mime=mime
        )

    @app.post("/api/documents/web", status_code=201)
    def import_web(payload: dict):
        url = payload.get("url")
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError("URL không hợp lệ.")
        body, mime, final_url = fetch_public(url)
        mime = (
            "application/pdf"
            if body.startswith(b"%PDF-")
            else mime.split(";", 1)[0].strip().lower()
        )
        filename = Path(urlsplit(final_url).path).name or "web.html"
        parsed = parse_for_review(body, mime, filename)
        payload["title"] = payload.get("title") or urlsplit(final_url).hostname
        return store.create(
            body,
            parsed,
            payload,
            source_kind="web",
            filename=filename,
            mime=mime,
            source_url=final_url,
        )

    @app.patch("/api/documents/{document_id}")
    def edit(document_id: str, payload: dict):
        return store.update(document_id, payload)

    @app.post("/api/documents/{document_id}/decision")
    def decision(document_id: str, payload: dict):
        return store.decide(document_id, payload)

    @app.get("/api/documents/{document_id}/original")
    def original(document_id: str, inline: bool = False):
        doc = store.get(document_id)
        is_pdf = doc["mime"] == "application/pdf"
        return FileResponse(
            store.raw / doc["id"],
            media_type="application/pdf" if is_pdf else "text/plain; charset=utf-8",
            filename=doc["filename"],
            content_disposition_type="inline" if inline or is_pdf else "attachment",
        )

    @app.post("/api/search")
    def search(payload: dict):
        return store.search(
            payload.get("query", ""),
            payload.get("collection", "general"),
            payload.get("as_of"),
            payload.get("limit", 6),
        )

    @app.get("/api/export")
    def export(collection: str = "general", as_of: str | None = None):
        return JSONResponse(
            store.export(collection, as_of),
            headers={"Content-Disposition": 'attachment; filename="approved-rag.json"'},
        )

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
