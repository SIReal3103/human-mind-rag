"""BOT DATA: input là scope, KHÔNG phải câu hỏi của user.

Chạy: ./run-data.sh --scope 'Báo cáo số vụ án ma túy Việt Nam 2010-2015'
Hoặc: ./run-data.sh --brief-file examples/my-scope.txt
Tiếp tục lượt crawl đã có: ./run-data.sh --from-run bot-runs/<run-id>
Key OpenAI trong .env.local, dùng lại key đã cấu hình; không đưa key vào scope.
Output: bot-runs/<id>/data/{manifest.json,chunks.json,index.sqlite,llm-input.json}.
Manifest ready_partial = index dùng được, KHÔNG xác nhận scope đủ/chính xác.
LLM team gọi data_pipeline.retrieve(run_folder, user_question) lúc user hỏi.
Không cần câu hỏi để crawl/index. Không huấn luyện LLM, không sinh câu trả lời.
"""

import argparse
import json
import os
from pathlib import Path

from bot import ROOT, run_bot
from data_pipeline import build
from gateway import provider, setting


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scope")
    group.add_argument("--brief-file", type=Path)
    group.add_argument("--from-run", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "bot-runs")
    parser.add_argument("--max-sources", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument("--max-chunks", type=int, default=400)
    parser.add_argument(
        "--parser",
        choices=("auto", "docling", "native"),
        help="Local document parser; run setup-parser.sh once for Docling",
    )
    parser.add_argument(
        "--ocr",
        choices=("auto", "full", "off"),
        help="Docling OCR mode; auto preserves native PDF text",
    )
    parser.add_argument(
        "--document-max-pages",
        type=int,
        help="Docling initial page range (1–200); truncation is explicitly flagged",
    )
    parser.add_argument(
        "--embedding-model",
        default=setting("BTC_EMBEDDING_MODEL", "text-multilingual-embedding-002")
        if provider() == "btc"
        else setting("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=int(setting("EMBEDDING_DIMENSIONS", "768" if provider() == "btc" else "1536")),
    )
    args = parser.parse_args()
    if not (
        1 <= args.max_sources <= 20
        and 1 <= args.max_pages <= 100
        and 0 <= args.max_depth <= 3
        and 1 <= args.max_chunks <= 10000
        and 1 <= args.dimensions <= 3072
    ):
        parser.error("Invalid crawl/chunk/dimension limits")
    folder = args.from_run
    try:
        if args.from_run and any(
            value is not None for value in (args.parser, args.ocr, args.document_max_pages)
        ):
            parser.error(
                "--from-run rebuilds existing parsed data; parser/OCR flags require a fresh scope run"
            )
        for name, value in (
            ("DOCUMENT_PARSER", args.parser),
            ("DOCUMENT_OCR", args.ocr),
            ("DOCUMENT_MAX_PAGES", args.document_max_pages),
        ):
            if value is not None:
                os.environ[name] = str(value)
        from document_parser import parser_options, runtime

        if folder is None:
            options = parser_options()
            if options["mode"] == "docling" and not runtime().is_file():
                raise ValueError("DOCLING_NOT_INSTALLED: run ./setup-parser.sh")
            brief = args.scope or args.brief_file.read_text(encoding="utf-8")
            _, folder = run_bot(
                brief,
                args.output,
                args.max_sources,
                args.max_pages,
                args.max_depth,
                search_provider="openai",
                planner="model",
            )
        manifest = build(folder, args.embedding_model, args.dimensions, args.max_chunks)
        print(
            json.dumps(
                {
                    "status": manifest["status"],
                    "chunks": manifest["chunk_count"],
                    "output": str(Path(folder).resolve() / "data"),
                    "crawl_status": manifest["crawl_status"],
                },
                ensure_ascii=False,
            )
        )
        return 0 if manifest["chunk_count"] else 2
    except Exception as error:
        print(
            json.dumps(
                {"status": "failed", "error": str(error), "run": str(folder)}, ensure_ascii=False
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
