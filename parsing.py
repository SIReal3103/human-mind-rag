"""Local HTML table extraction. Cell strings and original locations stay intact."""

import re

from lxml import html

from engine import ValidationError


def html_article_text(document, extracted_text):
    """Recover a marked article body when precision extraction missed its prose."""
    tree = html.document_fromstring(document)
    body_names = {
        "article-body",
        "article-content",
        "story-body",
        "entry-content",
        "post-content",
        "content-detail",
    }
    excluded_names = {
        "related",
        "related-articles",
        "related-posts",
        "recommended",
        "comments",
        "share",
        "social-share",
        "sharing",
    }
    for element in list(tree.iterdescendants()):
        if not isinstance(element.tag, str):
            continue
        names = {
            value.lower().replace("_", "-")
            for value in (element.get("class", "") + " " + element.get("id", "")).split()
        }
        if element.tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "footer",
            "aside",
            "form",
        } or names.intersection(excluded_names):
            element.drop_tree()
    candidates = []
    existing = " ".join(extracted_text.split())
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        names = {
            value.lower().replace("_", "-")
            for value in (element.get("class", "") + " " + element.get("id", "")).split()
        }
        if not (
            element.tag == "article"
            or "articleBody" in element.get("itemprop", "").split()
            or names.intersection(body_names)
        ):
            continue
        paragraphs = [" ".join(p.text_content().split()) for p in element.xpath(".//p")]
        paragraphs = [text for text in paragraphs if len(text) >= 80]
        prose_size = sum(map(len, paragraphs))
        if len(paragraphs) < 2 or prose_size < 200:
            continue
        text_size = len(" ".join(element.text_content().split()))
        link_size = sum(len(" ".join(a.text_content().split())) for a in element.xpath(".//a"))
        if link_size > text_size / 4:
            continue
        retained = sum(len(text) for text in paragraphs if text in existing)
        if retained >= prose_size / 2:
            continue
        candidates.append((prose_size, text_size, element))
    if not candidates:
        return None
    element = max(candidates, key=lambda candidate: candidate[:2])[2]
    for node in element.iter():
        if node.tag in {
            "article",
            "div",
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "blockquote",
            "pre",
            "figure",
            "figcaption",
            "table",
            "tr",
        }:
            node.text = "\n" + (node.text or "")
            node.tail = "\n" + (node.tail or "")
        elif node.tag in {"br", "td", "th"}:
            node.tail = "\n" + (node.tail or "")
    return "\n".join(
        " ".join(line.split()) for line in element.text_content().splitlines() if line.strip()
    )


def html_article_leads(document):
    """Capture article lead/summary blocks that readability extractors may omit."""
    tree = html.fromstring(document)
    for element in tree.xpath("//script|//style|//noscript|//svg"):
        element.drop_tree()
    leads = []
    for element in tree.xpath("//article//*[@class]"):
        classes = set(re.split(r"[\s_-]+", element.get("class", "").lower()))
        if not classes.intersection({"lead", "brief", "sapo", "summary"}):
            continue
        text = " ".join(element.text_content().split())
        if not 60 <= len(text) <= 2000 or any(lead["text"] == text for lead in leads):
            continue
        leads.append({"text": text, "locator": tree.getroottree().getpath(element)})
        if len(leads) == 3:
            break
    return leads


def html_mathml_text(document):
    """Render bounded MathML into searchable text and retain the original markup."""
    tree = html.fromstring(document)
    maths = tree.xpath("//math[not(ancestor::math)]")
    if len(maths) > 300:
        raise ValidationError("HTML có quá 300 công thức; cần xử lý riêng và duyệt độ phủ")
    locations = [(node, tree.getroottree().getpath(node)) for node in maths]
    expressions = []

    def render(node, depth=0):
        if depth > 24:
            raise ValidationError("MathML lồng quá sâu")
        tag = node.tag.rsplit("}", 1)[-1].lower() if isinstance(node.tag, str) else ""
        children = [
            child
            for child in node
            if isinstance(child.tag, str) and child.tag.rsplit("}", 1)[-1] != "annotation-xml"
        ]
        if tag == "semantics":
            return render(children[0], depth + 1) if children else ""
        if tag in ("mi", "mn", "mo", "mtext"):
            return " ".join("".join(node.itertext()).split())
        values = [render(child, depth + 1) for child in children]
        if tag == "msup" and len(values) >= 2:
            return values[0] + "^{" + values[1] + "}"
        if tag == "msub" and len(values) >= 2:
            return values[0] + "_{" + values[1] + "}"
        if tag == "msubsup" and len(values) >= 3:
            return values[0] + "_{" + values[1] + "}^{" + values[2] + "}"
        if tag == "mfrac" and len(values) >= 2:
            return "(" + values[0] + ")/(" + values[1] + ")"
        if tag == "msqrt":
            return "sqrt(" + "".join(values) + ")"
        if tag == "mroot" and len(values) >= 2:
            return "root(" + values[0] + "," + values[1] + ")"
        if tag == "mspace":
            return " "
        if tag == "mtr":
            return "[" + ", ".join(values) + "]"
        if tag == "mtable":
            return "; ".join(values)
        return "".join(values)

    for node, locator in locations:
        markup = html.tostring(node, encoding="unicode", with_tail=False)
        if len(markup) > 8000:
            raise ValidationError("MathML vượt giới hạn 8.000 ký tự")
        value = " ".join(render(node).split())
        if not value or len(value) > 500:
            raise ValidationError("MathML không thể chuyển thành công thức ngắn để đối chiếu")
        expressions.append({"text": value, "locator": locator, "mathml": markup})
        replacement = html.Element("span")
        replacement.text = " " + value + " "
        replacement.tail = node.tail
        node.getparent().replace(node, replacement)
    return html.tostring(tree, encoding="unicode"), expressions


def html_tables(document):
    tree = html.fromstring(document)
    for element in tree.xpath("//script|//style|//noscript"):
        element.drop_tree()
    tables = tree.xpath(
        "//table[not(ancestor::table or ancestor::nav or ancestor::footer or ancestor::aside)]"
    )
    if len(tables) > 100:
        raise ValidationError("HTML quá 100 bảng")
    result = []
    for table in tables:
        path = tree.getroottree().getpath(table)
        rows = table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")
        cells, grid, occupied = [], [], {}
        if len(rows) > 1000:
            raise ValidationError("HTML table quá 1000 hàng")
        for row_index, row in enumerate(rows):
            column = 0
            for element in row.xpath("./th|./td"):
                while (row_index, column) in occupied:
                    column += 1
                try:
                    rowspan = int(element.get("rowspan", "1"))
                    colspan = int(element.get("colspan", "1"))
                except ValueError as error:
                    raise ValidationError("HTML table span không phải số nguyên") from error
                if rowspan == 0:  # HTML: span through the remaining rows of this group.
                    group_rows = element.getparent().getparent().xpath("./tr")
                    group_position = group_rows.index(row) if row in group_rows else row_index
                    rowspan = (
                        len(group_rows) - group_position if group_rows else len(rows) - row_index
                    )
                if not 1 <= rowspan <= 100 or not 1 <= colspan <= 100 or column + colspan > 100:
                    raise ValidationError("HTML table span/cột vượt giới hạn")
                if row_index + rowspan > len(rows):
                    raise ValidationError("HTML table rowspan vượt số hàng")
                text = " ".join(element.text_content().split())
                index = len(cells)
                if index >= 10000:
                    raise ValidationError("HTML table quá 10000 ô")
                cells.append(
                    {
                        "row": row_index,
                        "column": column,
                        "text": text,
                        "rowspan": rowspan,
                        "colspan": colspan,
                        "header": element.tag == "th",
                        "locator": tree.getroottree().getpath(element),
                    }
                )
                for r in range(row_index, row_index + rowspan):
                    for c in range(column, column + colspan):
                        if (r, c) in occupied:
                            raise ValidationError("HTML table ô gộp chồng nhau")
                        occupied[r, c] = index
                column += colspan
        width = max((c for _, c in occupied), default=-1) + 1
        if not cells:
            continue
        for r in range(len(rows)):
            grid.append([occupied.get((r, c)) for c in range(width)])
        headings = table.xpath("preceding::*[self::h1 or self::h2 or self::h3]")
        caption = " ".join(" ".join(table.xpath("./caption//text()")).split())
        result.append(
            {
                "caption": caption,
                "section": " ".join(headings[-1].text_content().split()) if headings else "",
                "locator": path,
                "cells": cells,
                "grid_cell_indices": grid,
                "row_count": len(rows),
                "column_count": width,
                "status": "extracted_structure_not_verified",
            }
        )
    return result
