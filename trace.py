"""Persisted provenance DAG, error evidence and bounded repair recommendations."""

import argparse
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from engine import ValidationError, save_json


class EvidenceError(ValidationError):
    def __init__(self, code, message, locator=None, expected=None, observed=None):
        super().__init__(message)
        self.code, self.locator = code, locator
        self.expected, self.observed = expected, observed


def remediation(code, stage):
    rules = {
        "AUTH_FAILED": ("search", "Sửa cấu hình key rồi chạy lại tìm nguồn; không retry key sai."),
        "COUNTRY_MISMATCH": (
            "discovery",
            "Loại nguồn sai quốc gia hoặc sửa mapping scope sau khi kiểm tra.",
        ),
        "INDICATOR_MISMATCH": (
            "discovery",
            "Chọn lại chỉ số khớp định nghĩa; không đổi số liệu để vượt gate.",
        ),
        "MISSING_YEARS": (
            "discovery",
            "Tìm nguồn bổ sung đủ năm; giữ null/thiếu, không tự điền 0.",
        ),
        "INVALID_VALUE": (
            "parse",
            "So sánh ô dữ liệu với bản gốc; nếu nguồn cũng thiếu thì tìm nguồn khác.",
        ),
        "DUPLICATE_YEAR": ("parse", "Kiểm tra bản gốc và phép ghép dòng trước khi loại trùng."),
        "OUT_OF_SCOPE_YEAR": ("parse", "Kiểm tra filter thời gian và dòng gốc."),
        "CROSSCHECK_MISMATCH": (
            "parse",
            "Đối chiếu hai bản tải và phiên bản dataset; chưa xác định parser hay nguồn sai.",
        ),
        "SOURCE_REVISION": (
            "check",
            "Review thay đổi nguồn so với snapshot; không tự sửa benchmark.",
        ),
    }
    restart, action = rules.get(
        code, (stage, "Kiểm tra bằng chứng và sửa công đoạn phát hiện lỗi trước khi chạy lại.")
    )
    return {
        "restart_from": restart,
        "action": action,
        "status": "pending",
        "max_attempts": 2,
        "auto_modify_facts": False,
    }


class TraceStore:
    def __init__(self, folder):
        self.folder, self.nodes, self.issues, self.stack = folder, [], [], []

    def node(self, stage, label, parents=None, refs=None, status="success"):
        parents = list(dict.fromkeys(parents if parents is not None else self.stack[-1:]))
        existing = {node["id"] for node in self.nodes}
        if any(parent not in existing for parent in parents):
            raise ValueError("Lineage parent does not exist")
        node = {
            "id": f"n{len(self.nodes) + 1:05d}",
            "stage": stage,
            "label": label,
            "parents": parents,
            "refs": refs or {},
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self.nodes.append(node)
        self.save()
        return node

    @contextmanager
    def stage(self, stage, label, parents=None, refs=None):
        node = self.node(stage, label, parents, refs, "running")
        self.stack.append(node["id"])
        try:
            yield node
        except Exception as error:
            node["status"] = "failed"
            # An exception may unwind through several parent stages: record the deepest detection only.
            issue_id = getattr(error, "trace_issue_id", None)
            if issue_id is None:
                code = getattr(error, "code", "STAGE_ERROR")
                if getattr(error, "code", None) in (401, 403):
                    code = "AUTH_FAILED"
                issue = {
                    "id": f"e{len(self.issues) + 1:05d}",
                    "code": str(code),
                    "detected_at": node["id"],
                    "detected_stage": stage,
                    "message": str(error),
                    "locator": getattr(error, "locator", None),
                    "expected": getattr(error, "expected", None),
                    "observed": getattr(error, "observed", None),
                    "cause_status": "unconfirmed",
                    "repair": remediation(str(code), stage),
                }
                self.issues.append(issue)
                issue_id = issue["id"]
                try:
                    error.trace_issue_id = issue_id
                except AttributeError:
                    pass
            node["issue_id"] = issue_id
            raise
        else:
            node["status"] = "success"
        finally:
            self.stack.pop()
            self.save()

    def artifact(self, path, parents=None, locator=None, stage="save"):
        raw = (self.folder / path).read_bytes()
        return self.node(
            stage,
            path,
            parents,
            {
                "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "locator": locator,
            },
        )

    def save(self):
        save_json(
            self.folder / "lineage.json", {"version": 1, "nodes": self.nodes, "issues": self.issues}
        )
        save_json(
            self.folder / "feedback.json",
            {
                "issues": self.issues,
                "note": "Detected stage is evidence, not proof of root cause. Repairs remain pending until rerun and revalidation.",
            },
        )


def explain(folder, target):
    graph = json.loads((folder / "lineage.json").read_text(encoding="utf-8"))
    by_id = {node["id"]: node for node in graph["nodes"]}
    issue = next((item for item in graph["issues"] if item["id"] == target), None)
    node_id = issue["detected_at"] if issue else target
    if node_id not in by_id:
        raise ValueError("Unknown node/error ID")
    order, visited = [], set()

    def walk(current):
        if current in visited:
            return
        visited.add(current)
        node = by_id[current]
        integrity = None
        if node["refs"].get("path") and node["refs"].get("sha256"):
            path = (folder / node["refs"]["path"]).resolve()
            if not path.is_relative_to(folder.resolve()):
                raise ValueError("Artifact path outside run folder")
            integrity = (
                path.exists()
                and hashlib.sha256(path.read_bytes()).hexdigest() == node["refs"]["sha256"]
            )
        order.append({**node, "artifact_integrity": integrity})
        for parent in node["parents"]:
            walk(parent)

    walk(node_id)
    affected = {node_id}
    for node in graph["nodes"]:
        if any(parent in affected for parent in node["parents"]):
            affected.add(node["id"])
    return {
        "target": target,
        "issue": issue,
        "backward_trace": order,
        "affected_descendants": sorted(affected - {node_id}),
        "cause_warning": "Chuỗi bằng chứng chỉ ra nơi phát hiện lỗi; nguyên nhân gốc có thể cần đối chiếu thêm.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Truy ngược một lỗi hoặc output về nguồn")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--target", required=True, help="Node n00001 hoặc error e00001")
    args = parser.parse_args()
    print(json.dumps(explain(args.run.resolve(), args.target), ensure_ascii=False, indent=2))
