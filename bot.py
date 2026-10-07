"""Scope -> discovery -> bounded crawl -> parse/check/save, with source provenance.

CÁCH DÙNG: ./run-data.sh --scope 'Phạm vi tài liệu cần thu thập'
Full data mode also builds chunks, embeddings, hybrid index and evidence context.
./run.sh --scope '...' runs only discovery/crawl/parse/check/save.
Neither ingestion command needs an end-user question or generates answers.

INPUT: arbitrary conceptual/statistical scope in Vietnamese/English, not 'đề F'.
Set --max-sources/--max-pages/--max-depth to bound the crawl.
OUTPUT: bot-runs/<id>/{scope,report,lineage,feedback}.json, raw/, parsed/.
Review is not verified truth; source and scope coverage can remain incomplete.

PARSER: ./setup-parser.sh once installs isolated Docling and local vi/en OCR models.
DOCUMENT_PARSER=docling requires that setup; auto uses it when installed.
Native mode uses pypdf without OCR/table structure. See README for limits.
Docling retains its native JSON, page/bbox references and uncertainty warnings.
No JavaScript rendering, CAPTCHA bypass or chat UI is included.

KEY/MODEL: configure the selected provider in .env.local; never put keys in scope.
OpenAI development and BTC competition profiles are separate, with fixed endpoints.
BTC capabilities stay gated until verified through a BTC key; no provider fallback.

TRUY NGƯỢC: python trace.py --run bot-runs/<id> --target <trace/error ID>
python audit_run.py --run bot-runs/<id> checks chunks/index/source preservation.
The detected stage is evidence, not proof of root cause. Repairs are recommendations.
Tests offline, live retrieval probes and parser visual checks prove different things.
"""

import argparse
import csv
import hashlib
import html
import io
import ipaddress
import json
import math
import re
import socket
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter, deque
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from engine import ValidationError, save_json, unpack_json, unpack_xml
from trace import EvidenceError, TraceStore


def traced(http, stage, label, function, *args, parents=None, refs=None, **kwargs):
    if not getattr(http, "trace", None):
        return function(*args, **kwargs), None
    with http.trace.stage(stage, label, parents=parents, refs=refs) as node:
        return function(*args, **kwargs), node["id"]


AGENT = "DeltaMindCrawler/0.3"
ROOT = Path(__file__).resolve().parent
TOPICS = {
    "population": ("dan so", "population"),
    "life expectancy": ("tuoi tho", "life expectancy"),
    "GDP": ("gdp", "tong san pham quoc noi"),
    "unemployment": ("that nghiep", "unemployment"),
    "inflation": ("lam phat", "inflation"),
}
COUNTRIES = {
    "VN": ("viet nam", "vietnam", "vnm"),
    "US": ("hoa ky", "united states", "usa"),
    "JP": ("nhat ban", "japan", "jpn"),
    "FR": ("phap", "france", "fra"),
}


def folded(value):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.lower().replace("đ", "d"))
            if not unicodedata.combining(c)
        ).split()
    )


def plan_scope(brief):
    text = folded(brief)
    # A topic and target are supplied by the user; a vague task title must not invent either.
    topic = next((key for key, aliases in TOPICS.items() if any(a in text for a in aliases)), None)
    country = next(
        (key for key, aliases in COUNTRIES.items() if any(a in text for a in aliases)), None
    )
    years = sorted(set(int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", brief)))
    if len(brief.strip()) < 2 or re.fullmatch(r"(?:de|bai)\s+[a-z0-9]{1,2}", text):
        raise ValidationError(
            "Scope chưa có chủ đề: hãy nêu nội dung cần thu thập, không chỉ nhập 'đề F'."
        )
    if len(brief) > 8000:
        raise ValidationError("Scope vượt 8000 ký tự: cần thu hẹp yêu cầu")
    subject = re.split(r"[.!?\n]", brief)[0].strip()
    start, end = (years[0], years[-1]) if years else (None, None)
    if start and end - start > 30:
        raise ValidationError("Scope lớn hơn 31 năm: cần thu hẹp phạm vi.")
    translations = {"VN": "Vietnam", "US": "United States", "JP": "Japan", "FR": "France"}
    english = " ".join(
        v
        for v in (
            translations.get(country),
            topic,
            str(start) if start else None,
            str(end) if end != start else None,
        )
        if v
    )
    query_subject = english if topic and country else subject
    statistical = bool(
        years
        or re.search(
            r"\b(?:ti le|ty le|so luong|so vu|thong ke|chi so|dataset|statistics|rate)\b",
            text,
        )
    )
    queries = list(
        dict.fromkeys(
            [
                query_subject,
                subject + (" số liệu thống kê" if statistical else " giáo trình giải thích"),
                query_subject + (" dataset csv" if statistical else " tài liệu PDF"),
            ]
        )
    )
    terms = [
        word
        for word in re.findall(r"[a-z0-9]+", text)
        if len(word) >= 3
        and word
        not in {
            "lieu",
            "thu",
            "thap",
            "theo",
            "tung",
            "nam",
            "giai",
            "doan",
            "thong",
            "ke",
            "nguon",
            "chinh",
            "thuc",
        }
    ]
    return {
        "brief": brief,
        "subject": subject,
        "topic": topic,
        "country": country,
        "start_year": start,
        "end_year": end,
        "scope_kind": "statistical" if statistical else "conceptual",
        "queries": queries,
        "terms": list(dict.fromkeys(terms)),
    }


def canonical_url(url):
    p = urllib.parse.urlsplit(html.unescape(url.strip()))
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValidationError("URL không phải HTTP(S) công khai")
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    return urllib.parse.urlunsplit(
        (
            p.scheme.lower(),
            p.netloc.lower(),
            p.path or "/",
            urllib.parse.urlencode(sorted(query)),
            "",
        )
    )


def check_public_url(url):
    p = urllib.parse.urlsplit(canonical_url(url))
    if p.port not in (None, 80, 443):
        raise ValidationError("Chỉ cho phép cổng HTTP/HTTPS tiêu chuẩn")
    addresses = socket.getaddrinfo(
        p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM
    )
    if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
        raise ValidationError("Chặn địa chỉ nội bộ/private/loopback")


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.current, self.title, self.in_title = [], None, "", False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.current = {"href": attrs["href"], "title": "", "class": attrs.get("class", "")}
        if tag == "title":
            self.in_title = True

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] += data
        if self.in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append(self.current)
            self.current = None
        if tag == "title":
            self.in_title = False


def search_links(document):
    if "anomaly.js" in document or "anomaly-modal" in document:
        raise ValidationError("Search bị CAPTCHA; không vượt qua CAPTCHA")
    parser = PageLinks()
    parser.feed(document)
    results, seen = [], set()
    for link in parser.links:
        if "result-link" not in link["class"] and "result__a" not in link["class"]:
            continue
        u = urllib.parse.urlsplit(link["href"])
        target = urllib.parse.parse_qs(u.query).get("uddg", [link["href"]])[0]
        try:
            target = canonical_url(target)
        except ValidationError:
            continue
        if target not in seen:
            results.append({"url": target, "title": " ".join(link["title"].split())})
            seen.add(target)
    if not results:
        raise ValidationError("Search không trả link kết quả hợp lệ")
    return results


def relevance(value, plan):
    if plan.get("concepts"):
        from semantic import concept_score

        return concept_score(value, plan)
    text = folded(value)
    topic = plan["topic"]
    topic_match = bool(topic and any(alias in text for alias in TOPICS[topic]))
    country_match = bool(
        plan["country"] and any(alias in text for alias in COUNTRIES[plan["country"]])
    )
    keyword_hits = sum(term in text for term in plan["terms"])
    return 4 * topic_match + 3 * country_match + min(keyword_hits, 4)


def source_priority(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    # Publisher category, not proof that an individual assertion is true.
    if host == "worldbank.org" or host.endswith(".worldbank.org"):
        return 4, "World Bank; tổ chức công bố dữ liệu, vẫn cần kiểm tra nội dung"
    if host.endswith(".gov.vn") or host.endswith(".gov"):
        return 4, "Tên miền chính phủ; vẫn cần kiểm tra phạm vi và định nghĩa"
    if any(
        host == root or host.endswith("." + root)
        for root in ("un.org", "unodc.org", "who.int", "oecd.org")
    ):
        return 3, "Tổ chức quốc tế; vẫn cần kiểm tra nguồn gốc dữ liệu"
    return 0, "Nguồn khác; nội dung chưa được xác minh, đưa vào review"


class PublicHTTP:
    def __init__(self, folder, timeout=15, max_bytes=10_000_000, trace=None):
        self.folder, self.timeout, self.max_bytes = folder, timeout, max_bytes
        self.trace, self.trace_parent = trace, None
        self.manifest, self.robots, self.last_request = [], {}, {}
        owner = self

        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                check_public_url(newurl)
                if not newurl.endswith("/robots.txt"):
                    owner.ensure_robots(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirect())

    def checkpoint(self):
        save_json(self.folder.parent / "fetch-manifest.json", self.manifest)

    def ensure_robots(self, url):
        p = urllib.parse.urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots:
            parser = urllib.robotparser.RobotFileParser(origin + "/robots.txt")
            # Sentinel prevents recursion when robots itself redirects.
            self.robots[origin] = (parser, 0.6, "pending")
            try:
                body, _ = self.fetch(origin + "/robots.txt", kind="robots", robots=False)
                if body.lstrip().startswith(b"<"):
                    raise ValidationError("robots.txt trả HTML; chưa xác định được quyền crawl")
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
                delay = max(float(parser.crawl_delay(AGENT) or parser.crawl_delay("*") or 0), 0.6)
                rate = parser.request_rate(AGENT) or parser.request_rate("*")
                if rate:
                    delay = max(delay, rate.seconds / rate.requests)
                self.robots[origin] = (parser, delay, "checked")
            except urllib.error.HTTPError as error:
                if error.code not in (404, 410):
                    self.robots[origin] = (parser, 0.6, "unavailable")
                    raise ValidationError(
                        f"Không kiểm tra được robots.txt: {error.code}"
                    ) from error
                parser.parse(["User-agent: *", "Allow: /"])
                self.robots[origin] = (parser, 0.6, "not_present")
            except Exception:
                self.robots[origin] = (parser, 0.6, "unavailable")
                raise
        parser, delay, status = self.robots[origin]
        if status in ("pending", "unavailable") or not parser.can_fetch(AGENT, url):
            raise ValidationError("robots.txt chặn hoặc chưa xác định được quyền crawl")
        if delay > 30:
            raise ValidationError("Crawl-delay vượt giới hạn thời gian lượt thử")
        return origin, delay

    def fetch(self, url, kind="page", robots=True):
        if not self.trace:
            return self._fetch(url, kind, robots)
        parents = self.trace.stack[-1:] or ([self.trace_parent] if self.trace_parent else [])
        with self.trace.stage("crawl", kind, parents=parents, refs={"url": url}) as node:
            body, record = self._fetch(url, kind, robots)
            artifact = self.trace.artifact(record["raw_path"], parents=[node["id"]], stage="crawl")
            record["trace_id"] = artifact["id"]
            self.checkpoint()
            return body, record

    def _fetch(self, url, kind="page", robots=True):
        url = canonical_url(url)
        check_public_url(url)
        origin, delay = (
            self.ensure_robots(url) if robots else (urllib.parse.urlsplit(url).netloc, 0.6)
        )
        record = {"url": url, "kind": kind, "status": "failed", "errors": []}
        self.manifest.append(record)
        try:
            for attempt in range(1, 3):
                record["attempts"] = attempt
                wait = delay - (time.monotonic() - self.last_request.get(origin, 0))
                if wait > 0:
                    time.sleep(wait)
                self.last_request[origin] = time.monotonic()
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": AGENT,
                            "Accept": "text/html,application/json,application/xml,text/xml,application/pdf,text/csv,text/plain",
                        },
                    )
                    with self.opener.open(request, timeout=self.timeout) as response:
                        check_public_url(response.url)
                        content_type = response.headers.get_content_type()
                        body = response.read(self.max_bytes + 1)
                        if len(body) > self.max_bytes:
                            raise ValidationError("Phản hồi vượt giới hạn 10 MB")
                        extension = {
                            "text/html": "html",
                            "application/json": "json",
                            "application/pdf": "pdf",
                            "text/csv": "csv",
                            "application/xml": "xml",
                            "text/xml": "xml",
                        }.get(content_type, "txt")
                        digest = hashlib.sha256(body).hexdigest()
                        name = f"{len(self.manifest):03d}-{kind}-{digest[:12]}.{extension}"
                        (self.folder / name).write_bytes(body)
                        record.update(
                            {
                                "status": "success",
                                "final_url": response.url,
                                "http_status": response.status,
                                "content_type": content_type,
                                "charset": response.headers.get_content_charset() or "utf-8",
                                "bytes": len(body),
                                "sha256": digest,
                                "raw_path": f"raw/{name}",
                                "fetched_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    return body, record
                except urllib.error.HTTPError as error:
                    record.update({"http_status": error.code})
                    record["errors"].append(str(error))
                    if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                        raise
                    retry_after = error.headers.get("Retry-After", "")
                    if retry_after and (not retry_after.isdigit() or int(retry_after) > 30):
                        raise
                    time.sleep(max(2**attempt, int(retry_after or 0)))
                except (urllib.error.URLError, TimeoutError) as error:
                    record["errors"].append(str(error))
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)
        except Exception as error:
            record["error"] = str(error)
            raise
        finally:
            self.checkpoint()


def discover(http, plan, search_provider="auto"):
    from gateway import gateway_key, search_gateway

    provider = (
        "openai"
        if search_provider == "openai" or (search_provider == "auto" and gateway_key())
        else "duckduckgo"
    )
    candidates, by_url, searches = [], {}, []
    for query in plan["queries"]:
        entry = {"query": query, "provider": provider, "status": "failed"}
        searches.append(entry)
        try:

            def do_search(query=query):
                if provider == "openai":
                    return search_gateway(
                        query,
                        http.folder,
                        len(searches),
                        {
                            "scope": plan["brief"],
                            "metric": plan.get("metric"),
                            "exclusions": plan.get("exclusions", []),
                        },
                    )
                url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
                body, record = http.fetch(url, kind="search")
                return search_links(body.decode(record["charset"], errors="replace")), {
                    "raw_path": record["raw_path"]
                }

            (results, evidence), search_id = traced(
                http,
                "search",
                query,
                do_search,
                parents=[http.trace_parent] if http.trace_parent else None,
                refs={"query": query, "provider": provider},
            )
            if search_id:
                artifact = http.trace.artifact(
                    evidence["raw_path"], parents=[search_id], stage="search"
                )
                entry["trace_id"] = artifact["id"]
            entry.update({"status": "success", "result_count": len(results), **evidence})
            for result in results:
                try:
                    result = {**result, "url": canonical_url(result["url"])}
                except ValidationError:
                    continue
                if result["url"] not in by_url:
                    priority, reason = source_priority(result["url"])
                    score = relevance(
                        result["title"] + " " + urllib.parse.unquote(result["url"]), plan
                    )
                    candidate = {
                        **result,
                        "search_queries": [query],
                        "relevance_score": score,
                        "publisher_priority": priority,
                        "publisher_reason": reason,
                        "decision": "candidate" if score >= 3 else "rejected",
                        "reason": "Có tín hiệu khớp scope; cần kiểm tra nội dung"
                        if score >= 3
                        else "Không đủ tín hiệu khớp scope",
                    }
                    if search_id:
                        candidate["lineage_ids"] = [entry["trace_id"]]
                    by_url[result["url"]] = candidate
                    candidates.append(candidate)
                else:
                    by_url[result["url"]]["search_queries"].append(query)
                    if search_id:
                        by_url[result["url"]]["lineage_ids"].append(entry["trace_id"])
        except Exception as error:
            entry["error"] = str(error)
            entry["issue_id"] = getattr(error, "trace_issue_id", None)
        save_json(
            http.folder.parent / "discovery.json",
            {"plan": plan, "searches": searches, "candidates": candidates},
        )
        if "CAPTCHA" in entry.get("error", ""):
            break
        if provider == "openai" and (
            "401" in entry.get("error", "")
            or "403" in entry.get("error", "")
            or "Chưa có key" in entry.get("error", "")
        ):
            break
    if searches and not candidates and all(s["status"] == "failed" for s in searches):
        reason = searches[-1].get("error", "Không có kết quả hợp lệ")
        raise ValidationError(
            "Không thể tìm nguồn: mọi truy vấn đã thất bại. "
            + reason[:200]
            + ". Xem discovery.json để kiểm tra từng truy vấn."
        )
    if plan.get("planner") == "model" and candidates:
        from semantic import rank_request

        (ranked, evidence), ranking_id = traced(
            http,
            "check",
            "Xếp nguồn theo scope thực tế",
            rank_request,
            plan,
            candidates,
            http.folder,
            parents=[i for c in candidates for i in c.get("lineage_ids", [])],
        )
        ranking_artifact = http.trace.artifact(
            evidence["raw_path"], parents=[ranking_id], stage="check"
        )
        for result in ranked:
            candidate = candidates[result["id"]]
            candidate.update(
                {
                    "semantic_relation": result["relation"],
                    "decision": "rejected" if result["relation"] == "irrelevant" else "candidate",
                    "reason": result["reason"],
                }
            )
            candidate.setdefault("lineage_ids", []).append(ranking_artifact["id"])
    # Resolve a discovered publisher's catalog instead of guessing an indicator
    # ID or treating its homepage as a verified dataset.
    expand_worldbank_catalog(http, plan, candidates)
    candidates.sort(
        key=lambda c: (
            bool(c.get("catalog_verified")),
            {"direct": 2, "lead": 1}.get(c.get("semantic_relation"), 0),
            c["relevance_score"],
            c["publisher_priority"],
        ),
        reverse=True,
    )
    save_json(
        http.folder.parent / "discovery.json",
        {"plan": plan, "searches": searches, "candidates": candidates},
    )
    return candidates, searches


def expand_worldbank_catalog(http, plan, candidates):
    names = {
        "population": "population, total",
        "life expectancy": "life expectancy at birth, total (years)",
    }
    if plan["topic"] not in names or not plan["country"] or plan["start_year"] is None:
        return
    origins = [
        c
        for c in candidates
        if urllib.parse.urlsplit(c["url"]).hostname
        in {"data.worldbank.org", "datacatalog.worldbank.org", "databank.worldbank.org"}
    ]
    if not origins:
        return
    parents = list(dict.fromkeys(i for c in origins for i in c.get("lineage_ids", [])))
    try:
        with http.trace.stage(
            "discovery",
            "Tra catalog World Bank từ nguồn search",
            parents=parents,
            refs={"publisher_urls": [c["url"] for c in origins]},
        ):
            body, record = http.fetch(
                "https://api.worldbank.org/v2/indicator?format=json&source=2&per_page=2000",
                kind="catalog",
            )
            (meta, indicators), parsed_id = traced(
                http,
                "parse",
                "Catalog chỉ số WDI",
                unpack_json,
                body,
                parents=[record["trace_id"]],
                refs={"path": record["raw_path"]},
            )
            if int(meta.get("pages", 0)) != 1 or int(meta.get("total", -1)) != len(indicators):
                raise EvidenceError(
                    "INCOMPLETE_CATALOG", "Catalog chưa tải đủ; không chọn chỉ số", "$[0]"
                )
            matches = [
                i
                for i in indicators
                if folded(i.get("name", "")) == names[plan["topic"]]
                and str(i.get("source", {}).get("id")) == "2"
            ]
            if len(matches) != 1:
                raise EvidenceError(
                    "AMBIGUOUS_INDICATOR",
                    "Không có duy nhất chỉ số đúng định nghĩa",
                    "$[1]",
                    "one exact metric",
                    len(matches),
                )
            item = matches[0]
            if not re.fullmatch(r"[A-Za-z0-9_.]+", item["id"]):
                raise ValidationError("Catalog trả mã chỉ số không hợp lệ")
            verified = http.trace.node(
                "check",
                "Chỉ số catalog khớp định nghĩa scope",
                parents=[parsed_id],
                refs={"path": record["raw_path"], "indicator": item["id"], "name": item["name"]},
            )
            url = canonical_url(
                f"https://data.worldbank.org/indicator/{item['id']}?locations={plan['country']}"
            )
            existing = next((c for c in candidates if c["url"] == url), None)
            candidate = {
                "url": url,
                "title": item["name"],
                "decision": "candidate",
                "reason": "Tra catalog nguồn đã tìm thấy; chọn duy nhất chỉ số khớp định nghĩa, cần kiểm dữ liệu",
                "relevance_score": 20,
                "publisher_priority": 4,
                "publisher_reason": "World Bank catalog adapter",
                "catalog_verified": True,
                "search_queries": list(
                    dict.fromkeys(q for c in origins for q in c["search_queries"])
                ),
                "lineage_ids": [verified["id"]],
                "catalog_raw": record["raw_path"],
            }
            if existing:
                candidate["lineage_ids"] += existing.get("lineage_ids", [])
                existing.update(candidate)
            else:
                candidates.append(candidate)
    except Exception as error:
        # Search results remain available; catalog failure is retained in lineage/feedback.
        for origin in origins:
            origin["catalog_error"] = str(error)


def extract_document(body, content_type, charset, url, scope=None, parser_cache=None):
    from document_parser import should_use_docling, parse_document, document_type

    content_type = document_type(content_type, url, body)

    if should_use_docling(content_type, body):
        doc = parse_document(body, content_type, parser_cache)
        if doc.get("title") == "input":
            doc["title"] = (
                urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).stem) or "Document"
            )
        return doc
    if content_type == "application/pdf" or body.startswith(b"%PDF-"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted or len(reader.pages) > (500 if scope else 200):
            raise ValidationError("PDF mã hóa hoặc vượt giới hạn trang: cần pipeline riêng")
        pages = []
        parse_started = time.monotonic()
        partial = len(reader.pages) > 40 and scope is not None
        scanned = 0
        for number, page in enumerate(reader.pages, 1):
            if time.monotonic() - parse_started > 45:
                raise ValidationError("PDF parse vượt 45 giây: cần pipeline riêng")
            contents = page.get_contents()
            if contents and len(contents.get_data()) > 5_000_000:
                raise ValidationError("PDF content stream quá lớn")
            value = page.extract_text(extraction_mode="layout") or ""
            scanned += 1
            if partial:
                score = relevance(value, scope)
                if number <= 2 or score > 0:
                    pages.append({"page": number, "text": value, "scope_score": score})
                    pages = sorted(
                        pages, key=lambda p: (p["page"] <= 2, p["scope_score"]), reverse=True
                    )[:24]
            else:
                pages.append({"page": number, "text": value})
            if sum(len(p["text"]) for p in pages) > 600000:
                raise ValidationError("PDF text vượt 600000 ký tự: cần scope/parser riêng")
        pages.sort(key=lambda p: p["page"])
        text = "\n\n".join(p["text"] for p in pages)
        if len(text.strip()) < 150:
            raise ValidationError("PDF thiếu text; chạy ./setup-parser.sh để bật Docling/OCR")
        return {
            "title": str((reader.metadata or {}).get("/Title", "")),
            "text": text,
            "pages": pages,
            "links": [],
            "parser": "pypdf-layout-scope-v2" if partial else "pypdf-layout",
            "pdf_total_pages": len(reader.pages),
            "pdf_scanned_pages": scanned,
            "selected_pages": [p["page"] for p in pages],
            "parse_partial": partial,
            "coverage_note": "Only scope-selected pages retained; no full-document completeness claim"
            if partial
            else None,
            "parse_warnings": [
                "Native pypdf mode: no OCR/table structure; layout/formula fidelity needs review."
            ],
        }
    if content_type in ("text/html", "application/xhtml+xml"):
        import trafilatura

        text_html = body.decode(charset, errors="replace")
        if any(
            marker in text_html.lower()
            for marker in ("cf-chl-", "verify you are human", "captcha-container")
        ):
            raise ValidationError("Trang challenge/CAPTCHA; chưa crawl được nội dung")
        from parsing import html_article_leads, html_article_text, html_mathml_text, html_tables

        readable_html, math_expressions = html_mathml_text(text_html)
        result = trafilatura.extract(
            readable_html,
            url=url,
            output_format="json",
            include_tables=True,
            include_comments=False,
            include_links=False,
            favor_precision=True,
        )
        tables = html_tables(text_html)
        useful_tables = any(t["row_count"] >= 2 and t["column_count"] >= 2 for t in tables)
        article_text = html_article_text(
            readable_html, json.loads(result).get("text", "") if result else ""
        )
        if not result and not useful_tables and not article_text:
            raise ValidationError("Không trích được nội dung chính; có thể cần JavaScript")
        extracted = (
            json.loads(result)
            if result
            else {
                "text": "\n".join(
                    t["caption"] + "\n" + "\n".join(c["text"] for c in t["cells"]) for t in tables
                )
            }
        )
        parser = PageLinks()
        parser.feed(text_html)
        text = article_text or extracted.get("text", "")
        if len(text.strip()) < 150 and not useful_tables:
            raise ValidationError("Nội dung chính quá ngắn; không coi HTML shell là dữ liệu")
        leads = [
            lead
            for lead in html_article_leads(text_html)
            if folded(lead["text"]) not in folded(text)
        ]
        if leads:
            prefix = "\n\n".join(lead["text"] for lead in leads)
            for lead in leads:
                lead["char_start"] = prefix.index(lead["text"])
                lead["char_end"] = lead["char_start"] + len(lead["text"])
            text = prefix + "\n\n" + text
        missing_math = [
            expression for expression in math_expressions if expression["text"] not in text
        ]
        if missing_math:
            supplement = "\n\nCông thức MathML bổ sung từ trang gốc (cần đối chiếu XPath):\n"
            for expression in missing_math:
                supplement += f"{expression['text']} [{expression['locator']}]\n"
            text += supplement
        if len(text) > 600000:
            raise ValidationError("HTML text vượt 600000 ký tự")
        return {
            "title": extracted.get("title") or parser.title,
            "text": text,
            "published_at": extracted.get("date"),
            "links": parser.links,
            "parser": "trafilatura+html-tables-v2",
            "tables": tables,
            "html_leads": leads,
            "html_math": math_expressions,
        }
    if content_type in ("text/csv", "application/csv") or urllib.parse.urlsplit(url).path.endswith(
        ".csv"
    ):
        text = body.decode(
            "utf-8-sig" if charset.lower() in ("utf-8", "utf8") else charset, errors="strict"
        )
        dialect = csv.Sniffer().sniff(text[:8192])
        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows or len(rows) > 10000 or any(len(row) != len(rows[0]) for row in rows):
            raise ValidationError("CSV rỗng, quá lớn hoặc sai số cột")
        return {"title": "CSV", "text": text, "table": rows, "links": [], "parser": "csv"}
    if content_type == "application/json":
        data = json.loads(body)
        return {
            "title": "JSON",
            "text": json.dumps(data, ensure_ascii=False),
            "structured": data,
            "links": [],
            "parser": "json",
        }
    raise ValidationError(f"Chưa hỗ trợ content type: {content_type}")


def worldbank_candidate(url):
    p = urllib.parse.urlsplit(url)
    match = re.fullmatch(r"/indicator/([A-Za-z0-9_.]+)", p.path.rstrip("/"))
    if p.hostname != "data.worldbank.org" or not match:
        return None
    return match.group(1), urllib.parse.parse_qs(p.query).get("locations", [None])[0]


def check_series(meta, rows, plan, indicator_id, expected_iso3):
    if str(meta.get("sourceid")) != "2" or not meta.get("lastupdated"):
        raise EvidenceError(
            "DATASET_METADATA",
            "Dataset không phải WDI hoặc thiếu ngày cập nhật",
            "$[0]",
            "sourceid=2 and lastupdated",
            meta,
        )
    expected = set(range(plan["start_year"], plan["end_year"] + 1))
    seen, result = set(), []
    for position, row in enumerate(rows):
        if (
            row.get("country", {}).get("id") != plan["country"]
            or row.get("countryiso3code") != expected_iso3
        ):
            raise EvidenceError(
                "COUNTRY_MISMATCH",
                "Sai quốc gia của scope",
                f"$[1][{position}].country",
                {"id": plan["country"], "iso3": expected_iso3},
                {"country": row.get("country"), "iso3": row.get("countryiso3code")},
            )
        if row.get("indicator", {}).get("id") != indicator_id:
            raise EvidenceError(
                "INDICATOR_MISMATCH",
                "Sai chỉ số",
                f"$[1][{position}].indicator.id",
                indicator_id,
                row.get("indicator"),
            )
        try:
            year = int(row["date"])
        except (ValueError, TypeError, KeyError) as error:
            raise EvidenceError(
                "INVALID_YEAR",
                "Năm không hợp lệ",
                f"$[1][{position}].date",
                sorted(expected),
                row.get("date"),
            ) from error
        if year not in expected:
            raise EvidenceError(
                "OUT_OF_SCOPE_YEAR", "Sai năm", f"$[1][{position}].date", sorted(expected), year
            )
        if year in seen:
            raise EvidenceError(
                "DUPLICATE_YEAR", "Trùng năm", f"$[1][{position}].date", "unique year", year
            )
        value = row.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise EvidenceError(
                "INVALID_VALUE",
                "Giá trị null hoặc không phải số hữu hạn",
                f"$[1][{position}].value",
                "finite number",
                str(value),
            )
        if plan["topic"] == "population" and (value < 0 or int(value) != value):
            raise EvidenceError(
                "INVALID_VALUE",
                "Dân số phải là số đếm nguyên không âm",
                f"$[1][{position}].value",
                "nonnegative integer",
                value,
            )
        if plan["topic"] == "life expectancy" and not 0 < value < 130:
            raise EvidenceError(
                "INVALID_VALUE",
                "Tuổi thọ ngoài giới hạn kiểm tra",
                f"$[1][{position}].value",
                "0 < value < 130",
                value,
            )
        result.append(
            {
                "year": year,
                "value": value,
                "country": expected_iso3,
                "indicator": indicator_id,
                "source_unit": row.get("unit", ""),
                "raw_locator": f"$[1][{position}]",
            }
        )
        seen.add(year)
    if seen != expected:
        raise EvidenceError(
            "MISSING_YEARS",
            f"Thiếu năm: {sorted(expected - seen)}",
            "$[1]",
            sorted(expected),
            sorted(seen),
        )
    return sorted(result, key=lambda r: r["year"])


def crawl_worldbank(http, candidate, plan):
    indicator_id, location = worldbank_candidate(candidate["url"])
    if not plan["country"] or plan["start_year"] is None:
        raise ValidationError("Chưa xác định được quốc gia/năm để kiểm chứng bảng số liệu")
    if location and plan["country"] not in location.split(";"):
        raise EvidenceError(
            "COUNTRY_MISMATCH",
            "URL ứng viên sai quốc gia",
            "query.locations",
            plan["country"],
            location,
        )
    query = urllib.parse.urlencode({"format": "json", "source": 2})
    body, metadata_record = http.fetch(
        f"https://api.worldbank.org/v2/indicator/{indicator_id}?{query}", kind="metadata"
    )
    _, indicators = unpack_json(body)
    matches = [
        item
        for item in indicators
        if item["id"] == indicator_id and str(item["source"]["id"]) == "2"
    ]
    if len(matches) != 1:
        raise ValidationError("Metadata chỉ số mơ hồ")
    indicator = matches[0]
    # Require the actual indicator name to contain the topic, not merely its search title.
    if plan["topic"] and not any(
        alias in folded(indicator["name"]) for alias in TOPICS[plan["topic"]]
    ):
        raise ValidationError("Tên chỉ số không khớp chủ đề")
    if not indicator.get("sourceNote") or not indicator.get("sourceOrganization"):
        raise ValidationError("Thiếu định nghĩa hoặc nguồn gốc chỉ số")
    if plan["topic"] == "population" and folded(indicator["name"]) != "population, total":
        raise ValidationError("Scope dân số tổng: không nhận biến thể tỷ lệ hoặc nhóm tuổi")
    if (
        plan["topic"] == "life expectancy"
        and folded(indicator["name"]) != "life expectancy at birth, total (years)"
    ):
        raise ValidationError("Scope tuổi thọ tổng: không nhận biến thể giới tính")
    country_body, country_record = http.fetch(
        f"https://api.worldbank.org/v2/country/{plan['country']}?format=json",
        kind="country-metadata",
    )
    _, countries = unpack_json(country_body)
    if len(countries) != 1 or not countries[0].get("id"):
        raise ValidationError("Không xác định được ISO3 quốc gia")
    iso3 = countries[0]["id"]
    params = {"source": 2, "date": f"{plan['start_year']}:{plan['end_year']}", "per_page": 100}
    base = f"https://api.worldbank.org/v2/country/{plan['country']}/indicator/{indicator_id}"
    body, data_record = http.fetch(
        base + "?" + urllib.parse.urlencode({**params, "format": "json"}), kind="data"
    )
    data_parents = [data_record["trace_id"]] if data_record.get("trace_id") else None
    (meta, raw_rows), parsed_id = traced(
        http,
        "parse",
        "World Bank JSON",
        unpack_json,
        body,
        parents=data_parents,
        refs={"path": data_record["raw_path"], "parser": "worldbank-json-v1"},
    )
    rows, checked_id = traced(
        http,
        "check",
        "Scope và chất lượng từng dòng",
        check_series,
        meta,
        raw_rows,
        plan,
        indicator_id,
        iso3,
        parents=[parsed_id] if parsed_id else None,
        refs={"path": data_record["raw_path"]},
    )
    xml, xml_record = http.fetch(base + "?" + urllib.parse.urlencode(params), kind="crosscheck")
    (xml_meta, xml_rows), xml_parsed_id = traced(
        http,
        "parse",
        "World Bank XML",
        unpack_xml,
        xml,
        parents=[xml_record["trace_id"]] if xml_record.get("trace_id") else None,
        refs={"path": xml_record["raw_path"], "parser": "worldbank-xml-v1"},
    )
    checked, xml_checked_id = traced(
        http,
        "check",
        "Scope XML",
        check_series,
        xml_meta,
        xml_rows,
        plan,
        indicator_id,
        iso3,
        parents=[xml_parsed_id] if xml_parsed_id else None,
        refs={"path": xml_record["raw_path"]},
    )
    if [(r["year"], r["value"]) for r in rows] != [
        (r["year"], r["value"]) for r in checked
    ] or meta["lastupdated"] != xml_meta["lastupdated"]:
        raise EvidenceError(
            "CROSSCHECK_MISMATCH",
            "JSON/XML khác dữ liệu hoặc phiên bản",
            "$[1]",
            [(r["year"], r["value"]) for r in rows],
            [(r["year"], r["value"]) for r in checked],
        )
    crosscheck_id = None
    if getattr(http, "trace", None):
        crosscheck_id = http.trace.node(
            "check",
            "JSON/XML khớp",
            parents=[checked_id, xml_checked_id],
            refs={"paths": [data_record["raw_path"], xml_record["raw_path"]]},
        )["id"]
        cross_node = next(n for n in http.trace.nodes if n["id"] == crosscheck_id)
        cross_node["parents"].extend([metadata_record["trace_id"], country_record["trace_id"]])
    checks = [
        "Đúng quốc gia, chỉ số, năm và dataset",
        "Đủ năm, không trùng/null",
        "Hai parser JSON/XML khớp từng giá trị và phiên bản",
    ]
    benchmark_path = ROOT / "benchmarks/vietnam-population-2020-2024.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if (
        benchmark["country_iso3"] == iso3
        and benchmark["indicator_id"] == indicator_id
        and set(benchmark["values"]) == {str(r["year"]) for r in rows}
    ):
        if benchmark["values"] != {str(r["year"]): r["value"] for r in rows}:
            raise EvidenceError(
                "SOURCE_REVISION",
                "Khác snapshot DataBank đã kiểm tra; cần xem xét thay đổi nguồn",
                "$[1]",
                benchmark["values"],
                {str(r["year"]): r["value"] for r in rows},
            )
        checks.append("Khớp snapshot DataBank kiểm tra ngày 2026-10-06 (cùng dataset)")
    # Exercise a real scope gate without issuing an unrelated network request.
    control = json.loads(json.dumps(raw_rows))
    control[0]["country"]["id"] = "ZZ"
    try:
        check_series(meta, control, plan, indicator_id, iso3)
    except ValidationError:
        checks.append("Negative control sửa country bị chặn (dữ liệu mô phỏng)")
    else:
        raise ValidationError("Quality gate không chặn sai quốc gia")
    for row in rows:
        row.update(
            {
                "source_url": data_record["url"],
                "raw_path": data_record["raw_path"],
                "raw_sha256": data_record["sha256"],
                "dataset_updated": meta["lastupdated"],
            }
        )
        if getattr(http, "trace", None):
            row["trace_id"] = http.trace.node(
                "check",
                f"Observation {row['year']}",
                parents=[crosscheck_id],
                refs={
                    "path": row["raw_path"],
                    "sha256": row["raw_sha256"],
                    "locator": row["raw_locator"],
                    "value": row["value"],
                    "indicator": indicator_id,
                },
            )["id"]
    return {
        "status": "verified_against_source",
        "url": candidate["url"],
        "indicator": indicator,
        "rows": rows,
        "checks": checks,
        "metadata_raw": metadata_record["raw_path"],
        "xml_raw": xml_record["raw_path"],
        "limitation": "Các kiểm tra cùng nguồn World Bank; không xác nhận độc lập thực tế.",
    }


def report_html(folder, report):
    def esc(value):
        return html.escape(str(value))

    issues_html = "".join(
        f"<tr><td>{esc(i['id'])}</td><td>{esc(i['code'])}</td><td>{esc(i['detected_stage'])}</td><td>{esc(i.get('locator'))}</td><td>{esc(i['message'])}</td><td>{esc(i['repair']['action'])}</td></tr>"
        for i in report.get("issues", [])
    )
    candidate_rows = "".join(
        f"<tr><td><a href='{esc(c['url'])}'>{esc(c['title'])}</a></td><td>{esc(c['decision'])}</td><td>{esc(c['reason'])}</td></tr>"
        for c in report["candidates"]
    )
    document_rows = "".join(
        f"<tr><td><a href='{esc(d['url'])}'>{esc(d.get('title', d['url']))}</a></td><td>{esc(d['status'])}</td><td>{esc(d.get('reason', ''))}</td></tr>"
        for d in report["documents"]
    )
    series = ""
    for data in report["datasets"]:
        rows = "".join(
            f"<tr><td>{r['year']}</td><td>{r['value']:,}</td><td><a href='{esc(r['raw_path'])}'>{esc(r['raw_locator'])}</a></td></tr>"
            for r in data["rows"]
        )
        checks = "".join(f"<li>{esc(c)}</li>" for c in data["checks"])
        series += f"<h3>{esc(data['indicator']['name'])}</h3><p>{esc(data['indicator']['sourceNote'])}</p><ul>{checks}</ul><table><tr><th>Năm</th><th>Giá trị</th><th>Bằng chứng gốc</th></tr>{rows}</table><p>{esc(data['limitation'])}</p>"
    content = f"""<!doctype html><html lang='vi'><meta charset='utf-8'><title>Crawl bot — kết quả</title>
<style>body{{font:16px/1.65 system-ui;max-width:1100px;margin:32px auto;padding:0 24px;color:#14263c}}table{{border-collapse:collapse;width:100%;margin:16px 0}}td,th{{border:1px solid #ccd6e0;padding:10px;text-align:left;overflow-wrap:anywhere}}a{{color:#1665b5}}.badge{{padding:8px 16px;background:#e5eef8;border-radius:8px}}code{{background:#edf2f7}}</style>
<h1>Bot tự tìm nguồn và crawl</h1><p>{esc(report["plan"]["brief"])}</p><p class='badge'>{esc(report["status"])}</p>
<p>{esc(report["summary"])}</p><p>Lượt chạy UTC: {esc(report["run_at"])}</p>
<h2>Truy vấn tìm kiếm thực tế</h2><ul>{"".join("<li>" + esc(q) + "</li>" for q in report["plan"]["queries"])}</ul>
<h2>Bảng số liệu kiểm chứng theo nguồn</h2>{series or "<p>Chưa có bảng số liệu vượt qua kiểm tra. Không tự bịa dữ liệu thay thế.</p>"}
<h2>Quyết định nguồn</h2><table><tr><th>Nguồn</th><th>Trạng thái</th><th>Lý do</th></tr>{candidate_rows}</table>
<h2>Trang và tài liệu crawl</h2><table><tr><th>URL</th><th>Trạng thái</th><th>Ghi chú</th></tr>{document_rows}</table>
<h2>Truy ngược và phản hồi lỗi</h2><p><a href='lineage.json'>Chuỗi nguồn → crawl → parse → check → save</a> · <a href='feedback.json'>Kế hoạch sửa lỗi</a>. Mỗi observation có trace_id. Nơi phát hiện lỗi chưa nhất thiết là nguyên nhân gốc.</p><table><tr><th>ID</th><th>Mã lỗi</th><th>Bước phát hiện</th><th>Vị trí gốc</th><th>Lỗi</th><th>Xử lý</th></tr>{issues_html}</table>
<h2>Giới hạn</h2><p>Provider tìm kiếm: {esc(", ".join(sorted(set(s["provider"] for s in report.get("searches", [])))))}. Không có danh sách URL seed. Planner: {esc(report["plan"].get("planner", "rules"))}. Chế độ model lập query/khái niệm và xếp nguồn theo scope; quyết định của model chưa chứng minh sự thật. Điểm từ khóa/tên miền chỉ để ưu tiên, không chứng minh sự thật. Nội dung HTML/PDF/CSV ngoài connector số liệu nằm ở review. PDF/ảnh có thể dùng Docling/OCR local sau setup; cảnh báo parse và phần thiếu được giữ trong parsed data. Trang cần JavaScript hoặc CAPTCHA giữ lỗi; không vượt chặn. Báo cáo này mô tả bước crawl; xem data/manifest.json để biết trạng thái chunk/index khi chạy run-data.sh.</p>
<p><a href='report.json'>Báo cáo JSON</a> · <a href='discovery.json'>Bằng chứng tìm nguồn</a> · <a href='fetch-manifest.json'>Manifest</a> · <a href='observations.csv'>CSV kiểm chứng</a></p></html>"""
    (folder / "report.html").write_text(content, encoding="utf-8")


def run_bot(
    brief,
    output_root,
    max_sources=5,
    max_pages=12,
    max_depth=1,
    search_provider="auto",
    planner="rules",
):
    timestamp = datetime.now(timezone.utc)
    slug = hashlib.sha256(brief.encode()).hexdigest()[:10]
    folder = output_root / f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{slug}"
    (folder / "raw").mkdir(parents=True)
    (folder / "parsed").mkdir()
    trace = TraceStore(folder)
    with trace.stage("scope", "Yêu cầu đầu vào", parents=[], refs={"brief": brief}) as scope_node:
        plan = plan_scope(brief)
    http = PublicHTTP(folder / "raw", trace=trace)
    http.trace_parent = scope_node["id"]
    report = {
        "run_at": timestamp.isoformat(),
        "plan": plan,
        "status": "incomplete",
        "candidates": [],
        "documents": [],
        "datasets": [],
        "summary": "Đang xử lý",
        "lineage_file": "lineage.json",
        "feedback_file": "feedback.json",
    }
    save_json(folder / "scope.json", plan)
    trace.artifact("scope.json", parents=[scope_node["id"]], stage="scope")
    print("[scope] " + plan["subject"], flush=True)
    try:
        from gateway import gateway_key

        if planner == "model" or (
            planner == "auto" and search_provider != "duckduckgo" and gateway_key()
        ):
            from semantic import plan_request

            (plan, evidence), planner_id = traced(
                http,
                "scope",
                "Planner hiểu yêu cầu",
                plan_request,
                brief,
                plan,
                http.folder,
                parents=[scope_node["id"]],
            )
            planner_artifact = trace.artifact(
                evidence["raw_path"], parents=[planner_id], stage="scope"
            )
            http.trace_parent = planner_artifact["id"]
            report["plan"] = plan
            save_json(folder / "scope.json", plan)
            trace.artifact("scope.json", parents=[planner_artifact["id"]], stage="scope")
            print("[planner] " + plan["metric"], flush=True)
        else:
            plan["planner"] = "rules"
        candidates, searches = discover(http, plan, search_provider)
        report["candidates"], report["searches"] = candidates, searches
        chosen = [c for c in candidates if c["decision"] == "candidate"][:max_sources]
        for c in candidates:
            if c["decision"] == "candidate" and c not in chosen:
                c.update(
                    {"decision": "deferred", "reason": "Ngoài giới hạn số nguồn của lượt chạy"}
                )
        print(f"[discovery] {len(candidates)} nguồn tìm được; chọn {len(chosen)}", flush=True)
        queue = deque((c["url"], 0, c) for c in chosen)
        seen, hashes, series_seen = set(), set(), set()
        with closing(sqlite3.connect(folder / "crawl.sqlite")) as db, db:
            db.execute(
                "CREATE TABLE documents(url TEXT PRIMARY KEY,status TEXT,raw_path TEXT,parsed_path TEXT,reason TEXT)"
            )
            db.execute(
                "CREATE TABLE observations(country TEXT,indicator TEXT,year INTEGER,value REAL,source_url TEXT,raw_path TEXT,raw_locator TEXT,trace_id TEXT,PRIMARY KEY(country,indicator,year))"
            )
            while queue and len(seen) < max_pages:
                url, depth, candidate = queue.popleft()
                if url in seen:
                    continue
                seen.add(url)
                document = {
                    "url": url,
                    "depth": depth,
                    "status": "failed",
                    "title": candidate["title"],
                }
                origin = trace.node(
                    "discovery",
                    "Chọn URL",
                    parents=candidate.get("lineage_ids", [scope_node["id"]]),
                    refs={"url": url, "depth": depth},
                )
                document["trace_id"] = origin["id"]
                http.trace_parent = origin["id"]
                report["documents"].append(document)
                print(f"[crawl {len(seen)}/{max_pages}] {url}", flush=True)
                try:
                    wb = worldbank_candidate(url)
                    if wb and plan.get("planner") != "model" and wb not in series_seen:
                        dataset, dataset_node = traced(
                            http,
                            "check",
                            "World Bank connector",
                            crawl_worldbank,
                            http,
                            candidate,
                            plan,
                            parents=[origin["id"]],
                            refs={"url": url},
                        )
                        parsed_series = f"parsed/series-{len(report['datasets']) + 1}.json"
                        with trace.stage(
                            "save",
                            "Lưu bảng kiểm chứng",
                            parents=[r["trace_id"] for r in dataset["rows"]],
                            refs={"path": parsed_series},
                        ):
                            db.execute("SAVEPOINT save_series")
                            try:
                                for row in dataset["rows"]:
                                    db.execute(
                                        "INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?,?,?)",
                                        (
                                            row["country"],
                                            row["indicator"],
                                            row["year"],
                                            row["value"],
                                            row["source_url"],
                                            row["raw_path"],
                                            row["raw_locator"],
                                            row["trace_id"],
                                        ),
                                    )
                                save_json(folder / parsed_series, dataset)
                                trace.artifact(
                                    parsed_series, parents=[r["trace_id"] for r in dataset["rows"]]
                                )
                            except Exception:
                                db.execute("ROLLBACK TO save_series")
                                (folder / parsed_series).unlink(missing_ok=True)
                                raise
                            finally:
                                db.execute("RELEASE save_series")
                        series_seen.add(wb)
                        report["datasets"].append(dataset)
                        document.update(
                            {
                                "status": "verified_against_source",
                                "title": dataset["indicator"]["name"],
                                "reason": "; ".join(dataset["checks"]),
                            }
                        )
                        candidate.update(
                            {"decision": "verified_against_source", "reason": document["reason"]}
                        )
                    else:
                        body, record = http.fetch(url)
                        document["raw_path"] = record["raw_path"]
                        final_url = record["final_url"]
                        seen.add(canonical_url(final_url))
                        extracted, parse_id = traced(
                            http,
                            "parse",
                            "Trích nội dung tài liệu",
                            extract_document,
                            body,
                            record["content_type"],
                            record["charset"],
                            final_url,
                            plan,
                            parser_cache=ROOT / ".parser-cache",
                            parents=[record["trace_id"]],
                            refs={"path": record["raw_path"], "url": final_url},
                        )
                        # Keep parser output even if semantic checking later fails.
                        unassessed_path = (
                            f"parsed/unassessed-document-{len(report['documents']):03d}.json"
                        )
                        save_json(
                            folder / unassessed_path,
                            {
                                **extracted,
                                "url": final_url,
                                "raw_path": record["raw_path"],
                                "raw_sha256": record["sha256"],
                                "status": "unassessed",
                                "trace_id": parse_id,
                            },
                        )
                        unassessed_node = trace.artifact(unassessed_path, parents=[parse_id])
                        document["unassessed_path"] = unassessed_path
                        digest = hashlib.sha256(
                            json.dumps(
                                {
                                    "text": folded(extracted["text"]),
                                    "tables": extracted.get("tables"),
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ).encode()
                        ).hexdigest()
                        if digest in hashes:
                            document.update(
                                {
                                    "status": "duplicate",
                                    "reason": "Nội dung chính trùng trang đã lấy",
                                }
                            )
                        elif (
                            plan.get("planner") != "model"
                            and relevance(extracted["title"] + " " + extracted["text"], plan) < 3
                        ):
                            document.update(
                                {
                                    "status": "out_of_scope",
                                    "reason": "Nội dung tải về không đủ khớp scope",
                                }
                            )
                        else:
                            hashes.add(digest)
                            assessment = None
                            document_status = "review"
                            check_id = parse_id
                            if plan.get("planner") == "model":
                                from semantic import check_request

                                (assessment, evidence), check_id = traced(
                                    http,
                                    "check",
                                    "Kiểm chủ đề và trích dẫn bản parse",
                                    check_request,
                                    plan,
                                    extracted,
                                    http.folder,
                                    len(report["documents"]),
                                    parents=[unassessed_node["id"]],
                                )
                                assessment_artifact = trace.artifact(
                                    evidence["raw_path"], parents=[check_id], stage="check"
                                )
                                document_status = assessment["status"]
                            parsed_path = f"parsed/document-{len(report['documents']):03d}.json"
                            save_json(
                                folder / parsed_path,
                                {
                                    **extracted,
                                    "url": final_url,
                                    "raw_path": record["raw_path"],
                                    "raw_sha256": record["sha256"],
                                    "status": document_status,
                                    "assessment": assessment,
                                    "scope_score": relevance(extracted["text"], plan),
                                    "trace_id": check_id,
                                },
                            )
                            saved_node = trace.artifact(
                                parsed_path,
                                parents=[assessment_artifact["id"] if assessment else parse_id],
                            )
                            document["trace_id"] = saved_node["id"]
                            document.update(
                                {
                                    "status": document_status,
                                    "title": extracted["title"],
                                    "assessment": assessment,
                                    "parsed_path": parsed_path,
                                    "reason": "; ".join(assessment["missing"])
                                    if assessment
                                    else "Đã trích nội dung; chưa xác minh số liệu/ngữ nghĩa độc lập",
                                }
                            )
                            if depth < max_depth and document_status != "out_of_scope":
                                next_links = []
                                for link in extracted["links"]:
                                    try:
                                        target = canonical_url(
                                            urllib.parse.urljoin(final_url, link["href"])
                                        )
                                    except ValidationError:
                                        continue
                                    if (
                                        urllib.parse.urlsplit(target).hostname
                                        != urllib.parse.urlsplit(final_url).hostname
                                    ):
                                        continue
                                    if target in seen or any(
                                        part in target.lower()
                                        for part in ("/login", "/search", "wp-admin", "javascript:")
                                    ):
                                        continue
                                    score = relevance(
                                        link["title"] + " " + urllib.parse.unquote(target), plan
                                    )
                                    if score >= 3:
                                        next_links.append((score, target, link["title"]))
                                for _, target, title in sorted(next_links, reverse=True)[:3]:
                                    queue.append(
                                        (
                                            target,
                                            depth + 1,
                                            {
                                                "url": target,
                                                "title": title,
                                                "lineage_ids": [saved_node["id"]],
                                            },
                                        )
                                    )
                        if depth == 0:
                            candidate.update(
                                {"decision": document["status"], "reason": document["reason"]}
                            )
                except Exception as error:
                    document["reason"] = str(error)
                    document["issue_id"] = getattr(error, "trace_issue_id", None)
                    if depth == 0:
                        candidate.update({"decision": "failed", "reason": str(error)})
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)",
                    (
                        url,
                        document["status"],
                        document.get("raw_path"),
                        document.get("parsed_path"),
                        document.get("reason"),
                    ),
                )
                db.commit()
                save_json(folder / "report.json", report)
            report["pending_urls"] = [u for u, _, _ in queue if u not in seen]
            rows = [row for dataset in report["datasets"] for row in dataset["rows"]]
            if rows:
                with (folder / "observations.csv").open(
                    "w", newline="", encoding="utf-8"
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
                save_json(folder / "observations.json", rows)
                parents = [row["trace_id"] for row in rows]
                trace.artifact("observations.csv", parents=parents)
                trace.artifact("observations.json", parents=parents)
            trace.artifact(
                "crawl.sqlite",
                parents=[n["id"] for n in trace.nodes if n["stage"] == "save"]
                or [scope_node["id"]],
            )
            counts = Counter(d["status"] for d in report["documents"])
            report["counts"] = dict(counts)
            report["scope_ambiguities"] = plan.get("ambiguities", [])
            report["status"] = (
                "has_verified_data"
                if rows
                else "needs_review"
                if counts["review"]
                else "incomplete"
            )
            if plan.get("ambiguities"):
                report["status"] = "needs_clarification"
            report["summary"] = (
                f"Tìm {len(candidates)} nguồn; xử lý {len(report['documents'])} URL; "
                f"{len(report['datasets'])} bảng kiểm chứng theo nguồn, {len(rows)} dòng; "
                f"{counts['review']} tài liệu chờ kiểm tra, {counts['failed']} URL lỗi. "
                "Không coi các nguồn lỗi hoặc review là dữ liệu đã xác minh."
            )
            if plan.get("ambiguities"):
                report["summary"] += " Cần làm rõ: " + "; ".join(plan["ambiguities"])
    except Exception as error:
        report["error"] = str(error)
        report["summary"] = "Lượt chạy chưa hoàn tất: " + str(error)
    finally:
        report["issues"] = trace.issues
        report["trace_node_count"] = len(trace.nodes)
        save_json(folder / "report.json", report)
        http.checkpoint()
        trace.save()
        report_html(folder, report)
    print("[result] " + report["summary"], flush=True)
    print("[report] " + str(folder / "report.html"), flush=True)
    return report, folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nhập scope -> tự tìm nguồn -> crawl -> kiểm tra")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--scope", help="Mô tả chủ đề, đối tượng và thời gian; không cần URL")
    input_group.add_argument("--brief-file", type=Path, help="File UTF-8 mô tả scope")
    parser.add_argument("--output", type=Path, default=ROOT / "bot-runs")
    parser.add_argument("--max-sources", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument(
        "--search-provider", choices=("auto", "openai", "duckduckgo"), default="auto"
    )
    parser.add_argument(
        "--planner",
        choices=("auto", "model", "rules"),
        default="auto",
        help="auto: dùng planner model khi có key OpenAI; rules dành cho offline/legacy",
    )
    args = parser.parse_args()
    if (
        not 1 <= args.max_sources <= 20
        or not 1 <= args.max_pages <= 100
        or not 0 <= args.max_depth <= 3
    ):
        parser.error("Giới hạn: sources 1–20, pages 1–100, depth 0–3")
    brief = args.scope or args.brief_file.read_text(encoding="utf-8").strip()
    try:
        report, _ = run_bot(
            brief,
            args.output.resolve(),
            args.max_sources,
            args.max_pages,
            args.max_depth,
            args.search_provider,
            args.planner,
        )
    except ValidationError as error:
        parser.error(str(error))
    raise SystemExit(0 if report["status"] == "has_verified_data" else 2)
