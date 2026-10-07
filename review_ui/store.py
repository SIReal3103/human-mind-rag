"""Transactional review revisions and an approved-only local evidence index."""

import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from ingestion import UPSTREAM_COMMIT, make_chunks
from quality import assess
from auto_review import approval_mode


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def today():
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()


def canonical_date(value):
    if not isinstance(value, str):
        raise ValueError("Ngày phải có dạng YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Ngày phải có dạng YYYY-MM-DD.") from None
    if parsed.isoformat() != value:
        raise ValueError("Ngày phải có dạng YYYY-MM-DD.")
    return value


def folded(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
        if unicodedata.category(c) != "Mn"
    )


def metadata(values, base=None):
    result = dict(base or {})
    for key, limit, default in [
        ("title", 300, "Văn bản mới"),
        ("collection", 100, "general"),
        ("source_id", 200, ""),
        ("document_version", 100, "1"),
    ]:
        value = values.get(key, result.get(key, default))
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"{key} không hợp lệ (tối đa {limit} ký tự).")
        result[key] = value.strip() or default
    if "time_sensitive" in values and not isinstance(values["time_sensitive"], bool):
        raise ValueError("time_sensitive phải là boolean.")
    result["time_sensitive"] = values.get("time_sensitive", result.get("time_sensitive", False))
    for key in ("effective_from", "effective_to"):
        value = values.get(key, result.get(key)) or None
        if value:
            if not isinstance(value, str):
                raise ValueError("Ngày hiệu lực phải có dạng YYYY-MM-DD.")
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                raise ValueError("Ngày hiệu lực phải có dạng YYYY-MM-DD.") from None
            if value != parsed.isoformat():
                raise ValueError("Ngày hiệu lực phải có dạng YYYY-MM-DD.")
        result[key] = value
    if result["effective_to"] and not result["effective_from"]:
        raise ValueError("Có ngày kết thúc thì cần ngày bắt đầu hiệu lực.")
    if result["effective_to"] and result["effective_to"] <= result["effective_from"]:
        raise ValueError(
            "Ngày kết thúc phải sau ngày bắt đầu; ngày kết thúc không nằm trong kỳ hiệu lực."
        )
    return result


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.raw = self.folder / "originals"
        self.raw.mkdir(exist_ok=True)
        self.database = self.folder / "review.sqlite"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS evidence USING fts5(
                    document_id UNINDEXED, chunk_id UNINDEXED, content,
                    tokenize='unicode61 remove_diacritics 2'
                );
            """)

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.database, timeout=15)
        try:
            db.execute("PRAGMA busy_timeout=15000")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _get(self, db, document_id):
        row = db.execute("SELECT payload FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            raise KeyError("Không tìm thấy tài liệu.")
        return json.loads(row[0])

    def _all(self, db):
        return [
            json.loads(row[0])
            for row in db.execute("SELECT payload FROM documents ORDER BY rowid DESC")
        ]

    def _save(self, db, doc):
        db.execute(
            "INSERT INTO documents VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (doc["id"], json.dumps(doc, ensure_ascii=False)),
        )

    def get(self, document_id):
        with self.connect() as db:
            return self._get(db, document_id)

    def list(self, status=None):
        with self.connect() as db:
            docs = self._all(db)
        return [d for d in docs if not status or d["status"] == status]

    def summaries(self, status=None):
        """Keep parser JSON and full text out of queue/list responses."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT json_remove(payload, '$.parser_evidence', '$.text', '$.segments', "
                "'$.chunks', '$.audit') FROM documents "
                "WHERE ? IS NULL OR json_extract(payload, '$.status') = ? ORDER BY rowid DESC",
                (status, status),
            )
            return [json.loads(row[0]) for row in rows]

    def create(
        self, body, parsed, values, *, source_kind, filename, mime, source_url=None, crawl=None
    ):
        doc = metadata(values)
        document_id = uuid4().hex
        digest = hashlib.sha256(body).hexdigest()
        stamp = now()
        doc.update(
            id=document_id,
            source_kind=source_kind,
            filename=filename,
            mime=mime,
            source_url=source_url,
            source_sha256=digest,
            status="pending",
            revision=1,
            created_at=stamp,
            updated_at=stamp,
            text=parsed["text"],
            parser=parsed["parser"],
            segments=parsed.get("segments", []),
            parser_evidence=parsed.get("parser_evidence", {}),
            parser_warnings=parsed.get("warnings", []),
            partial=parsed.get("partial", False),
            edited=False,
            chunker="scope-data-bot/char-span-v1/400",
            upstream_commit=UPSTREAM_COMMIT,
            duplicate_of=None,
            audit=[
                {
                    "action": "import",
                    "actor": "local-operator",
                    "note": "Nhập vào hàng chờ duyệt.",
                    "at": stamp,
                    "revision": 1,
                    "source_sha256": digest,
                }
            ],
        )
        if crawl is not None:
            doc["crawl"] = crawl
        doc["source_id"] = doc["source_id"] or "source-" + digest[:16]
        doc["chunks"] = make_chunks(doc["text"], doc["segments"]) if doc["text"].strip() else []
        original = self.raw / document_id
        original.write_bytes(body)
        try:
            with self.connect(write=True) as db:
                duplicate = next(
                    (
                        d
                        for d in self._all(db)
                        if d["source_sha256"] == digest and d["collection"] == doc["collection"]
                    ),
                    None,
                )
                doc["duplicate_of"] = duplicate["id"] if duplicate else None
                doc["quality"] = assess(doc)
                self._save(db, doc)
        except BaseException:
            original.unlink(missing_ok=True)
            raise
        return doc

    def update(self, document_id, values):
        # Chunk work runs before acquiring the write lock; revision is checked again inside.
        old = self.get(document_id)
        if type(values.get("revision")) is not int or old["revision"] != values["revision"]:
            raise Conflict("Tài liệu đã thay đổi. Tải lại trước khi sửa hoặc duyệt.")
        if old["status"] != "pending":
            raise Conflict("Chỉ sửa bản chờ duyệt. Tạo phiên bản mới nếu tài liệu đã được duyệt.")
        updated = metadata(values, old)
        updated["source_id"] = updated["source_id"] or old["source_id"]
        replaced_partial = False
        if "text" in values:
            if not isinstance(values["text"], str) or len(values["text"]) > 600_000:
                raise ValueError("Nội dung phải là văn bản, tối đa 600.000 ký tự.")
            if values["text"] != old["text"]:
                updated["text"] = values["text"]
                updated["edited"] = True
                updated["segments"] = []
                updated["parser_evidence"] = {}
                updated["parser"] = "human-edited-text-v1"
                updated["chunks"] = (
                    make_chunks(updated["text"], None) if updated["text"].strip() else []
                )
                if old.get("partial"):
                    replaced_partial = True
                    updated["partial"] = False
                    updated["parser_warnings"] = [
                        *old.get("parser_warnings", []),
                        "Nội dung đã thay thế bản trích xuất thiếu. Người duyệt cần đối chiếu "
                        "toàn bộ bản gốc và xác nhận nội dung thay thế đã đầy đủ trước khi duyệt.",
                    ]
        with self.connect(write=True) as db:
            current = self._get(db, document_id)
            if current["revision"] != old["revision"]:
                raise Conflict("Tài liệu đã thay đổi. Tải lại trước khi lưu.")
            updated["revision"] += 1
            updated["updated_at"] = now()
            updated["quality"] = assess(updated)
            updated["audit"].append(
                {
                    "action": "edit",
                    "actor": "local-operator",
                    "note": (
                        "Thay bản trích xuất thiếu bằng nội dung hiệu chỉnh; giữ nguyên nguồn gốc "
                        "và cảnh báo để người duyệt đối chiếu đầy đủ."
                        if replaced_partial
                        else "Cập nhật bản chờ duyệt; giữ nguyên nguồn gốc."
                    ),
                    "at": updated["updated_at"],
                    "revision": updated["revision"],
                    "content_sha256": hashlib.sha256(updated["text"].encode()).hexdigest(),
                    **(
                        {"previous_parser": old["parser"], "previous_partial": old["partial"]}
                        if replaced_partial
                        else {}
                    ),
                }
            )
            self._save(db, updated)
        return updated

    def decide(self, document_id, values):
        action = values.get("action")
        if not isinstance(action, str) or action not in ("approve", "reject", "reopen", "withdraw"):
            raise ValueError("Quyết định không hợp lệ.")
        actor = values.get("actor", "")
        note = values.get("note", "")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError("Điền tên người duyệt (tối đa 120 ký tự).")
        if not isinstance(note, str) or len(note) > 3000:
            raise ValueError("Ghi chú quá dài.")
        if action in ("reject", "withdraw") and not note.strip():
            raise ValueError("Cần ghi lý do từ chối hoặc thu hồi.")
        with self.connect(write=True) as db:
            doc = self._get(db, document_id)
            if type(values.get("revision")) is not int or values["revision"] != doc["revision"]:
                raise Conflict("Phiên bản duyệt đã cũ. Tải lại để kiểm nội dung hiện tại.")
            target = {
                ("pending", "approve"): "approved",
                ("pending", "reject"): "rejected",
                ("rejected", "reopen"): "pending",
                ("approved", "withdraw"): "withdrawn",
            }.get((doc["status"], action))
            if not target:
                raise Conflict("Thao tác không hợp lệ với trạng thái hiện tại.")
            if action == "approve":
                if values.get("approval_mode") == "automatic":
                    from auto_review import blockers, ACTOR

                    reasons = blockers(doc)
                    if reasons or actor != ACTOR:
                        raise ValueError("Không đủ điều kiện tự động duyệt: " + "; ".join(reasons))
                doc["quality"] = assess(doc)
                findings = doc["quality"]["findings"]
                if not doc["chunks"] or any(f["severity"] == "error" for f in findings):
                    raise ValueError("Còn lỗi chặn. Sửa tài liệu trước khi duyệt.")
                if (
                    any(f["severity"] == "warning" for f in findings)
                    and values.get("acknowledge_findings") is not True
                ):
                    raise ValueError("Cần xác nhận đã đối chiếu các cảnh báo với nguồn.")
                for other in self._all(db):
                    if (
                        other["id"] == doc["id"]
                        or other["status"] != "approved"
                        or other["collection"] != doc["collection"]
                    ):
                        continue
                    if other["source_id"] == doc["source_id"]:
                        if other["document_version"] == doc["document_version"]:
                            raise Conflict("Nguồn/phiên bản này đã được duyệt. Dùng phiên bản mới.")
                        if (doc.get("effective_from") or "0001-01-01") < (
                            other.get("effective_to") or "9999-12-31"
                        ) and (other.get("effective_from") or "0001-01-01") < (
                            doc.get("effective_to") or "9999-12-31"
                        ):
                            raise Conflict(
                                "Nguồn có bản đã duyệt chồng hiệu lực. Thu hồi bản cũ hoặc nhập khoảng hiệu lực không chồng nhau."
                            )
                    if other["text"] == doc["text"]:
                        raise Conflict("Nội dung này đã có trong kho. Không lập chỉ mục trùng.")
                db.executemany(
                    "INSERT INTO evidence(document_id,chunk_id,content) VALUES(?,?,?)",
                    [(document_id, c["id"], folded(c["text"])) for c in doc["chunks"]],
                )
            if action == "withdraw":
                db.execute("DELETE FROM evidence WHERE document_id=?", (document_id,))
            doc["status"] = target
            doc["revision"] += 1
            doc["updated_at"] = now()
            doc["audit"].append(
                {
                    "action": action,
                    "actor": actor.strip(),
                    "note": note.strip(),
                    "at": doc["updated_at"],
                    "revision": doc["revision"],
                    "source_sha256": doc["source_sha256"],
                    "content_sha256": hashlib.sha256(doc["text"].encode()).hexdigest(),
                    "acknowledge_findings": values.get("acknowledge_findings") is True,
                    "approval_mode": "automatic"
                    if values.get("approval_mode") == "automatic"
                    else "manual",
                }
            )
            self._save(db, doc)
        return doc

    def eligible(self, doc, collection, as_of):
        return (
            doc["status"] == "approved"
            and doc["collection"] == collection
            and (not doc.get("effective_from") or doc["effective_from"] <= as_of)
            and (not doc.get("effective_to") or as_of < doc["effective_to"])
        )

    def search(self, query, collection="general", as_of=None, limit=6):
        as_of = as_of or today()
        if (
            not isinstance(as_of, str)
            or not isinstance(collection, str)
            or not collection.strip()
            or len(collection) > 100
        ):
            raise ValueError("Bộ tài liệu hoặc ngày truy hồi không hợp lệ.")
        canonical_date(as_of)
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("Câu tìm kiếm cần 1–2.000 ký tự.")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Số kết quả phải từ 1 đến 20.")
        terms = list(dict.fromkeys(re.findall(r"\w+", folded(query))))[:24]
        match = " OR ".join('"' + term + '"' for term in terms)
        results = []
        if match:
            with self.connect() as db:
                # Join before LIMIT so documents from other collections cannot crowd out results.
                rows = db.execute(
                    """SELECT e.document_id,e.chunk_id,bm25(evidence) FROM evidence e
                    JOIN documents d ON d.id=e.document_id
                    WHERE evidence MATCH ? AND json_extract(d.payload,'$.status')='approved'
                    AND json_extract(d.payload,'$.collection')=?
                    AND (json_extract(d.payload,'$.effective_from') IS NULL OR json_extract(d.payload,'$.effective_from')<=?)
                    AND (json_extract(d.payload,'$.effective_to') IS NULL OR ?<json_extract(d.payload,'$.effective_to'))
                    ORDER BY bm25(evidence) LIMIT ?""",
                    (match, collection, as_of, as_of, limit),
                ).fetchall()
                budget = 24_000
                for document_id, chunk_id, score in rows:
                    doc = self._get(db, document_id)
                    chunk = next(c for c in doc["chunks"] if c["id"] == chunk_id)
                    if len(chunk["text"]) > budget:
                        break
                    budget -= len(chunk["text"])
                    results.append(
                        {
                            "document_id": doc["id"],
                            "title": doc["title"],
                            "source_id": doc["source_id"],
                            "document_version": doc["document_version"],
                            "source_url": doc["source_url"],
                            "source_sha256": doc["source_sha256"],
                            "chunk_id": chunk_id,
                            "text": chunk["text"],
                            "locator": chunk["locator"],
                            "score": -score,
                            "approval_mode": approval_mode(doc),
                            "factual_confidence": "automatically_approved_not_fact_verified"
                            if approval_mode(doc) == "automatic"
                            else "human_reviewed_not_guaranteed",
                        }
                    )
        return {
            "mode": "fts5",
            "status": "ok" if results else "no_evidence",
            "as_of": as_of,
            "collection": collection,
            "results": results,
            "notice": "Điểm lexical ranking không phải độ tin cậy nội dung.",
        }

    def export(self, collection="general", as_of=None):
        as_of = as_of or today()
        if (
            not isinstance(as_of, str)
            or not isinstance(collection, str)
            or not collection.strip()
            or len(collection) > 100
        ):
            raise ValueError("Bộ tài liệu hoặc ngày xuất không hợp lệ.")
        canonical_date(as_of)
        with self.connect() as db:
            docs = [d for d in self._all(db) if self.eligible(d, collection, as_of)]
        return {
            "schema": "delta-mind-approved-rag-v1",
            "exported_at": now(),
            "as_of": as_of,
            "collection": collection,
            "retrieval_mode": "fts5",
            "documents": docs,
        }
