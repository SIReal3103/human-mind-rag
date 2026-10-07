"""Independent output audit: hash/locator/content/vector consistency, not factual truth."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from data_pipeline import tokens, valid_vector
from engine import save_json
from trace import explain


def docling_fidelity(doc):
    """Check normalization against native Docling JSON, not correctness of OCR itself."""
    native = doc["docling_document"]

    def resolve(ref):
        value = native
        for part in ref.removeprefix("#/").split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value

    for page in doc.get("pages", []):
        for item in page.get("items", []):
            source = resolve(item["ref"])
            if item["provenance"] != source.get("prov", []):
                return False
            if not item["provenance"] or item["provenance"][0]["page_no"] != page["page"]:
                return False
            if item["label"] != "table" and page["text"][
                item["char_start"] : item["char_end"]
            ] != source.get("text", ""):
                return False
    for item in doc.get("unpaginated_items", []):
        source = resolve(item["ref"])
        if item["label"] != "table" and item["text"] != source.get("text", ""):
            return False
    for table in doc.get("tables", []):
        source = resolve(table["locator"])
        if table.get("provenance", []) != source.get("prov", []) or len(table["cells"]) != len(
            source["data"]["table_cells"]
        ):
            return False
        for cell, original in zip(table["cells"], source["data"]["table_cells"], strict=True):
            if (
                cell["text"],
                cell["row"],
                cell["column"],
                cell["rowspan"],
                cell["colspan"],
                cell["header"],
                cell.get("row_header", False),
                cell.get("bbox"),
            ) != (
                original["text"],
                original["start_row_offset_idx"],
                original["start_col_offset_idx"],
                original["end_row_offset_idx"] - original["start_row_offset_idx"],
                original["end_col_offset_idx"] - original["start_col_offset_idx"],
                original.get("column_header", False),
                original.get("row_header", False),
                original.get("bbox"),
            ):
                return False
    return True


def audit(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "data/manifest.json").read_text())
    chunks = json.loads((folder / "data/chunks.json").read_text())
    checks = []

    def check(label, passed):
        checks.append({"check": label, "pass": bool(passed)})

    check(
        "index hash",
        hashlib.sha256((folder / "data/index.sqlite").read_bytes()).hexdigest()
        == manifest["index_sha256"],
    )
    check("unique chunk IDs", len({c["id"] for c in chunks}) == len(chunks))
    with closing(
        sqlite3.connect((folder / "data/index.sqlite").as_uri() + "?mode=ro", uri=True)
    ) as db:
        rows = {
            ident: (json.loads(metadata), json.loads(vector))
            for ident, metadata, vector in db.execute("SELECT * FROM chunks")
        }
    check("manifest/chunks/index counts", len(rows) == len(chunks) == manifest["chunk_count"])
    documents = {}
    for chunk in chunks:
        ident = chunk["id"]
        metadata, vector = rows[ident]
        valid_vector(vector, manifest["dimensions"])
        check(ident + " index metadata", metadata == chunk)
        check(
            ident + " token budget",
            tokens(chunk["text"]) == chunk["tokens"] and chunk["tokens"] <= 500,
        )
        if chunk["parsed_path"] not in documents:
            documents[chunk["parsed_path"]] = json.loads(
                (folder / chunk["parsed_path"]).read_text()
            )
            if documents[chunk["parsed_path"]].get("parser") == "docling-local-v1":
                try:
                    correct = docling_fidelity(documents[chunk["parsed_path"]])
                except (KeyError, ValueError, TypeError, IndexError):
                    correct = False
                check(chunk["parsed_path"] + " native Docling normalization", correct)
        doc = documents[chunk["parsed_path"]]
        loc = chunk["locator"]
        prefix = chunk.get("prefix", doc.get("title", "")[:300] + "\n")
        body = chunk["text"][len(prefix) :]
        check(ident + " prefix", chunk["text"].startswith(prefix))
        if loc.get("field") == "text":
            check(
                ident + " original text span",
                body == doc["text"][loc["char_start"] : loc["char_end"]],
            )
        elif "page" in loc:
            page = next(p for p in doc["pages"] if p["page"] == loc["page"])
            check(
                ident + " original page span",
                body == page["text"][loc["char_start"] : loc["char_end"]],
            )
        elif loc.get("representation") == "row_with_headers":
            row = json.loads(body)
            table = doc["tables"][loc["table"]]
            grid = table["grid_cell_indices"][loc["row"]]
            check(
                ident + " row and column positions",
                row["row"] == loc["row"] and len(row["cells"]) == len(grid),
            )
            for cell in row["cells"]:
                source_index = grid[cell["column"]]
                check(
                    ident + " source cell " + str(cell["column"]),
                    source_index == cell["cell_index"]
                    and cell["text"]
                    == (table["cells"][source_index]["text"] if source_index is not None else None),
                )
        elif "row" in loc and "table" not in loc:
            text = json.dumps(doc["rows"][loc["row"]], ensure_ascii=False)
            check(ident + " source observation", body == text[loc["char_start"] : loc["char_end"]])
        else:
            check(ident + " unsupported locator", False)
        back = explain(folder, chunk["trace_id"])
        check(
            ident + " lineage hashes",
            all(n["artifact_integrity"] is not False for n in back["backward_trace"]),
        )
    result = {
        "status": "pass" if all(c["pass"] for c in checks) else "fail",
        "chunks": len(chunks),
        "checks": checks,
        "limitations": "Validates preservation and lineage against saved parser output. Does not independently verify source facts, source authority or parser fidelity to rendered PDF/HTML.",
    }
    save_json(folder / "data/audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run)
    print(
        json.dumps(
            {
                "status": result["status"],
                "chunks": result["chunks"],
                "checks": len(result["checks"]),
            }
        )
    )
    raise SystemExit(0 if result["status"] == "pass" else 2)
