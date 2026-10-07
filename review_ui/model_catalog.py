"""Task-compatible model routing, sourced from BTC's pricing and API guides."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

STAGES = ("planner", "search", "check", "embedding", "evidence")
TEXT_STAGES = ("planner", "search", "check", "evidence")
SOURCE = "https://docs.thucchien.ai/docs/round-2/user-guide/pricing"
OPENAI = (
    "gpt-6-luna",
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-6-sol",
    "gpt-6.1-sol",
    "gpt-6-astra",
    "o3",
    "o4-mini",
)
GEMINI = (
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
)
DEEPSEEK = ("deepseek-flash", "deepseek-v4-pro")
EMBEDDINGS = {
    "text-multilingual-embedding-002": ("google", 768),
    "text-embedding-005": ("google", 768),
    "gemini-embedding-001": ("google", 3072),
    "gemini-embedding-2": ("google", 3072),
    "text-embedding-3-small": ("openai", 1536),
    "text-embedding-3-large": ("openai", 3072),
}


def catalog():
    models = []
    for provider, names in (("openai", OPENAI), ("google", GEMINI), ("deepseek", DEEPSEEK)):
        for name in names:
            models.append(
                {
                    "id": name,
                    "provider": provider,
                    "stages": list(
                        TEXT_STAGES if provider != "deepseek" else ("planner", "check", "evidence")
                    ),
                    "groups": ["btc", "external"],
                }
            )
    for name, (provider, dimensions) in EMBEDDINGS.items():
        models.append(
            {
                "id": name,
                "provider": provider,
                "dimensions": dimensions,
                "stages": ["embedding"],
                "groups": ["btc"]
                if name in ("text-multilingual-embedding-002", "text-embedding-005")
                else ["btc", "external"],
            }
        )
    # Retain explicitly chosen historical OpenAI models when preparing old jobs.
    models.append(
        {
            "id": "gpt-4.1-mini",
            "provider": "openai",
            "stages": list(TEXT_STAGES),
            "groups": ["external"],
        }
    )
    return {
        "models": models,
        "defaults": {
            g: {
                s: ("text-multilingual-embedding-002" if g == "btc" else "text-embedding-3-small")
                if s == "embedding"
                else ("gpt-6-luna" if g == "btc" else "gpt-4.1-mini")
                for s in STAGES
            }
            for g in ("btc", "external")
        },
        "source": SOURCE,
        "as_of": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat(),
    }


def configuration(group="btc", models=None):
    if group not in ("btc", "external") or (models is not None and not isinstance(models, dict)):
        raise ValueError("Chọn bộ key BTC hoặc Ngoài và model cho từng bước.")
    models = models or {}
    if set(models) - set(STAGES):
        raise ValueError("Bước model không được hỗ trợ.")
    data = catalog()
    selected = {**data["defaults"][group], **models}
    routes = {}
    for stage, name in selected.items():
        entry = next(
            (
                m
                for m in data["models"]
                if m["id"] == name and group in m["groups"] and stage in m["stages"]
            ),
            None,
        )
        if entry is None:
            raise ValueError(f"Model không hỗ trợ bước {stage} trong bộ key đã chọn.")
        routes[stage] = {**entry, "provider": "btc" if group == "btc" else entry["provider"]}
    return {
        "key_group": group,
        "stage_models": selected,
        "stage_providers": {s: r["provider"] for s, r in routes.items()},
        "dimensions": routes["embedding"]["dimensions"],
    }


def normalize_scope(scope, as_of):
    # Resolve the user's relative end date once; both rules and model see the same year.
    return re.sub(
        r"\b(?:đến|tới|cho đến)\s+(?:hiện\s+(?:nay|tại)|bây giờ|nay)\b",
        "đến năm " + as_of[:4],
        scope,
        flags=re.IGNORECASE,
    )


def planner_contract(task, schema, scope):
    years = sorted({int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", scope)})
    first, last = (years[0], years[-1]) if years else (None, None)
    expected = {"start_year": first, "end_year": last}
    properties = {**schema["properties"]}
    for name, value in expected.items():
        properties[name] = (
            {"type": "null"} if value is None else {"type": "integer", "enum": [value]}
        )
    task += f"\nRàng buộc thời gian đã trích từ phạm vi: start_year={first}, end_year={last}. Giữ nguyên hai giá trị này; không tự suy diễn năm khác."
    return task, {**schema, "properties": properties}
