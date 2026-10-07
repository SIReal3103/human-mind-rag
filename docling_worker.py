"""Isolated Docling conversion; imports heavyweight libraries only in the worker.

--download-models is explicit setup. Normal conversion uses local weights only.
Native Docling structure and original page/bounding-box references are retained.
"""

import importlib.metadata
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import zipfile

VERSION = "2.134.0"


def normalize_table(item, document, section):
    data = item.data
    rows, columns = data.num_rows, data.num_cols
    if rows > 1000 or columns > 100 or len(data.table_cells) > 10000:
        raise ValueError("DOCLING_TABLE_LIMIT")
    grid = [[None] * columns for _ in range(rows)]
    cells = []
    warnings = []
    for cell in data.table_cells:
        r, c = cell.start_row_offset_idx, cell.start_col_offset_idx
        row_end, column_end = cell.end_row_offset_idx, cell.end_col_offset_idx
        if not 0 <= r < row_end <= rows or not 0 <= c < column_end <= columns:
            raise ValueError("DOCLING_TABLE_COORDINATES")
        index = len(cells)
        cells.append(
            {
                "row": r,
                "column": c,
                "text": cell.text,
                "rowspan": row_end - r,
                "colspan": column_end - c,
                "header": cell.column_header,
                "row_header": cell.row_header,
                "locator": item.self_ref,
                "bbox": cell.bbox.model_dump(mode="json") if cell.bbox else None,
            }
        )
        if not cell.column_header and re.search(r"\d[.,]?\d*\s+\d", cell.text):
            warnings.append(
                {
                    "cell_index": index,
                    "code": "MULTIPLE_NUMERIC_VALUES",
                    "message": "May contain merged physical rows or a formatted number; compare original. Do not split/choose a value automatically.",
                }
            )
        for row in range(r, row_end):
            for column in range(c, column_end):
                if grid[row][column] is not None:
                    raise ValueError("DOCLING_TABLE_OVERLAP")
                grid[row][column] = index
    missing = [[r, c] for r, row in enumerate(grid) for c, index in enumerate(row) if index is None]
    if missing:
        warnings.append(
            {
                "code": "MISSING_GRID_CELLS",
                "positions": missing,
                "message": "No recognized cell at these coordinates; retain null, compare original.",
            }
        )
    return {
        "caption": item.caption_text(document),
        "section": section,
        "locator": item.self_ref,
        "provenance": [p.model_dump(mode="json") for p in item.prov],
        "cells": cells,
        "grid_cell_indices": grid,
        "row_count": rows,
        "column_count": columns,
        "status": "extracted_structure_not_verified",
        "warnings": warnings,
    }


def normalize_document(document, options, total_pages, conversion_status):
    page_map, tables, unlocated = {}, [], []
    section, title = "", ""
    for item, _ in document.iterate_items(with_groups=False):
        label = str(item.label.value)
        if label in ("section_header", "title"):
            section = getattr(item, "text", "")
            if not title and label == "title":
                title = section
        if label == "table":
            tables.append(normalize_table(item, document, section))
            text = item.export_to_markdown(doc=document)
        else:
            text = getattr(item, "text", "")
        if not text.strip():
            continue
        provenance = [p.model_dump(mode="json") for p in item.prov]
        # Each item appears once in text. Multi-page table provenance retains every page.
        number = item.prov[0].page_no if item.prov else None
        record = {
            "ref": item.self_ref,
            "label": label,
            "section": section,
            "provenance": provenance,
            "text": text,
        }
        if number is None:
            unlocated.append(record)
        else:
            page_map.setdefault(number, []).append(record)
    pages = []
    for number, items in sorted(page_map.items()):
        parts, offset = [], 0
        for record in items:
            text = record.pop("text")
            record.update({"char_start": offset, "char_end": offset + len(text)})
            parts.append(text)
            offset += len(text) + 2
        pages.append({"page": number, "text": "\n\n".join(parts), "items": items})
    # Office backends without page provenance are kept as unpaginated text, never page 1 guesses.
    text = "\n\n".join([p["text"] for p in pages] + [r["text"] for r in unlocated])
    if not text.strip() or len(text) > 600_000:
        raise ValueError("DOCLING_EMPTY_OR_OVERSIZED_TEXT")
    partial = total_pages > options["max_pages"] or conversion_status != "success"
    return {
        "title": title or document.name,
        "text": text,
        "pages": pages if not unlocated else [],
        "unpaginated_items": unlocated,
        "links": [],
        "tables": tables,
        "parser": "docling-local-v1",
        "parser_library_version": VERSION,
        "parser_config": options,
        "docling_document": document.export_to_dict(),
        "pdf_total_pages": total_pages or None,
        "selected_pages": [p["page"] for p in pages],
        "parse_partial": partial,
        "conversion_status": conversion_status,
        "coverage_note": "Only the configured initial page range was converted; incomplete coverage."
        if total_pages > options["max_pages"]
        else "Docling reported partial conversion; inspect original."
        if partial
        else None,
        "parse_warnings": [
            "OCR/layout/table output requires comparison with original; not fact-verified.",
            "Formula and picture-description enrichment are disabled; mathematical notation needs review.",
        ],
    }


def download_models():
    from docling.utils.model_downloader import download_models as download
    from docling.datamodel.settings import settings
    from engine import save_json

    download(
        with_code_formula=False,
        with_picture_classifier=False,
        with_rapidocr=False,
        with_easyocr=True,
        easyocr_languages=["vi", "en"],
    )
    model_root = settings.cache_dir / "models"
    files = {}
    for path in sorted(model_root.rglob("*")):
        if path.is_file() and ".cache" not in path.parts:
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            files[str(path.relative_to(model_root))] = digest.hexdigest()
    manifest = {"docling": VERSION, "ocr_languages": ["vi", "en"], "files": files}
    save_json(Path(__file__).parent / ".parser-models.json", manifest)
    print("Local layout/table/EasyOCR vi,en models ready.")


def convert(source, options):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions, OcrMode
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    from docling.datamodel.settings import settings
    from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption

    if importlib.metadata.version("docling") != VERSION:
        raise ValueError("DOCLING_VERSION_MISMATCH: reinstall pinned parser requirements")
    if source.suffix in (".docx", ".pptx", ".xlsx"):
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > 1000 or sum(m.file_size for m in members) > 50_000_000:
                raise ValueError("DOCLING_ARCHIVE_LIMIT: Office uncompressed size/member count")
    elif source.suffix != ".pdf":
        from PIL import Image

        with Image.open(source) as image:
            if image.width * image.height > 20_000_000 or getattr(image, "n_frames", 1) > 1:
                raise ValueError("DOCLING_IMAGE_LIMIT: maximum 20 megapixels, single frame")
    total = 0
    if source.suffix == ".pdf":
        import pypdfium2

        with pypdfium2.PdfDocument(source) as pdf:
            total = len(pdf)
        if total > 500:
            raise ValueError("DOCLING_PAGE_LIMIT: PDF exceeds 500 pages")
    options_pdf = PdfPipelineOptions()
    options_pdf.artifacts_path = settings.cache_dir / "models"
    options_pdf.document_timeout = float(options["timeout"])
    options_pdf.enable_remote_services = False
    options_pdf.do_ocr = options["ocr"] != "off"
    options_pdf.do_table_structure = True
    options_pdf.ocr_options = EasyOcrOptions(
        lang=options["languages"],
        download_enabled=False,
        mode=OcrMode.FULL_PAGE if options["ocr"] == "full" else OcrMode.DEFAULT,
    )
    options_pdf.accelerator_options = AcceleratorOptions(
        num_threads=options["threads"], device=AcceleratorDevice.CPU
    )
    converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.IMAGE,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.XLSX,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options_pdf),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options_pdf),
        },
    )
    started = time.monotonic()
    result = converter.convert(
        source,
        max_file_size=10_000_000,
        page_range=(1, options["max_pages"]),
        raises_on_error=False,
    )
    if result.status.value not in ("success", "partial_success"):
        raise ValueError(
            "DOCLING_CONVERSION_FAILED: check supported format and local model installation"
        )
    doc = normalize_document(result.document, options, total, result.status.value)
    doc["parse_seconds"] = round(time.monotonic() - started, 3)
    return doc


if __name__ == "__main__":
    if sys.argv[1:] == ["--download-models"]:
        download_models()
    else:
        source, output, config = map(Path, sys.argv[1:])
        try:
            result = convert(source, json.loads(config.read_text(encoding="utf-8")))
        except Exception as error:
            # Never serialize model prompts, machine paths or dependency stack traces.
            result = {
                "error": str(error)
                if str(error).startswith("DOCLING_")
                else "DOCLING_CONVERSION_ERROR: "
                + type(error).__name__
                + "; check local models/input"
            }
        output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
