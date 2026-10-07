"""Bounded, fail-closed World Bank ingestion pilot. Python standard library only."""

import argparse
from contextlib import closing
import csv
import hashlib
import html
import json
import math
import os
from uuid import uuid4
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


class ValidationError(ValueError):
    pass


def save_json(path, data):
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_api_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def require_api_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.worldbank.org"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or not parsed.path.startswith("/v2/")
    ):
        raise ValidationError("URL outside allowlisted HTTPS API")


class Fetcher:
    def __init__(self, folder):
        self.folder = folder
        self.manifest = []
        self.opener = urllib.request.build_opener(SafeRedirect())

    def fetch(self, url, name):
        require_api_url(url)
        record = {"url": url, "name": name, "status": "failed"}
        self.manifest.append(record)
        for attempt in range(1, 4):
            record["attempts"] = attempt
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "DeltaMind-RAG-Ingestion-Pilot/0.1",
                        "Accept": "application/json, application/xml, text/xml",
                    },
                )
                with self.opener.open(request, timeout=30) as response:
                    require_api_url(response.url)
                    body = response.read(8_000_001)
                    if len(body) > 8_000_000:
                        raise ValidationError("Response exceeds 8 MB limit")
                    content_type = response.headers.get_content_type()
                    expected = (
                        {"application/json"}
                        if name.endswith(".json")
                        else {"application/xml", "text/xml"}
                    )
                    if content_type not in expected:
                        raise ValidationError(f"Unexpected content type: {content_type}")
                    record.update(
                        {
                            "final_url": response.url,
                            "http_status": response.status,
                            "content_type": content_type,
                        }
                    )
                (self.folder / name).write_bytes(body)
                record.update(
                    {
                        "status": "success",
                        "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "raw_path": f"raw/{name}",
                    }
                )
                return body
            except urllib.error.HTTPError as error:
                record["error"] = str(error)
                if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise
                retry_after = error.headers.get("Retry-After", "")
                # Do not hammer a server that asks for a longer wait than this pilot permits.
                if retry_after and (not retry_after.isdigit() or int(retry_after) > 30):
                    raise
                time.sleep(max(2**attempt, int(retry_after or 0)))
            except (urllib.error.URLError, TimeoutError) as error:
                record["error"] = str(error)
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
            except Exception as error:
                record["error"] = str(error)
                raise


def unpack_json(body):
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise ValidationError("Invalid JSON") from error
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not isinstance(payload[0], dict)
        or not isinstance(payload[1], list)
    ):
        raise ValidationError("Unexpected API envelope, including possible API error")
    meta, rows = payload
    if int(meta.get("pages", 0)) != 1 or int(meta.get("page", 0)) != 1:
        raise ValidationError("Incomplete pagination: pilot requires one complete page")
    if int(meta.get("total", -1)) != len(rows):
        raise ValidationError("Reported total does not match fetched rows")
    return meta, rows


def discover_indicator(body, scope):
    _, catalog = unpack_json(body)
    matches = [
        item
        for item in catalog
        if item.get("name", "").casefold() == scope["indicator_name"].casefold()
        and str(item.get("source", {}).get("id")) == scope["source_id"]
    ]
    if len(matches) != 1:
        raise ValidationError(f"Expected one exact indicator match; found {len(matches)}")
    selected = matches[0]
    if not selected.get("sourceNote") or not selected.get("sourceOrganization"):
        raise ValidationError("Indicator is missing definition or upstream provenance")
    return selected, len(catalog)


def validate_rows(meta, rows, scope, indicator_id):
    if str(meta.get("sourceid")) != scope["source_id"]:
        raise ValidationError("Wrong dataset/source")
    if not meta.get("lastupdated"):
        raise ValidationError("Missing dataset update date")
    expected_years = set(range(scope["start_year"], scope["end_year"] + 1))
    seen, clean = set(), []
    for position, row in enumerate(rows):
        if (
            row.get("country", {}).get("id") != scope["country"]
            or row.get("countryiso3code") != scope["country_iso3"]
        ):
            raise ValidationError("Wrong country")
        if row.get("indicator", {}).get("id") != indicator_id:
            raise ValidationError("Wrong indicator")
        try:
            year = int(row["date"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError("Invalid year") from error
        if year not in expected_years or year in seen:
            raise ValidationError("Out-of-scope or duplicate year")
        value = row.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValidationError("Missing, nonfinite or negative value")
        if scope["value_kind"] == "nonnegative_integer" and value != int(value):
            raise ValidationError("Expected integer count")
        # Empty units must remain explicit; do not silently invent source metadata.
        clean.append(
            {
                "country": scope["country_iso3"],
                "year": year,
                "indicator": indicator_id,
                "value": value,
                "source_unit": row.get("unit", ""),
                "raw_locator": f"$[1][{position}]",
            }
        )
        seen.add(year)
    if seen != expected_years:
        raise ValidationError(f"Missing years: {sorted(expected_years - seen)}")
    return sorted(clean, key=lambda row: row["year"])


def unpack_xml(body):
    try:
        root = ET.fromstring(body)
        ns = {"wb": "http://www.worldbank.org"}
        rows = []
        for node in root.findall("wb:data", ns):
            value = node.findtext("wb:value", namespaces=ns)
            rows.append(
                {
                    "country": {"id": node.find("wb:country", ns).get("id")},
                    "countryiso3code": node.findtext("wb:countryiso3code", namespaces=ns),
                    "indicator": {"id": node.find("wb:indicator", ns).get("id")},
                    "date": node.findtext("wb:date", namespaces=ns),
                    "value": float(value) if value else None,
                    "unit": node.findtext("wb:unit", default="", namespaces=ns) or "",
                }
            )
        if int(root.get("pages", 0)) != 1 or int(root.get("total", -1)) != len(rows):
            raise ValidationError("Incomplete XML response")
        return dict(root.attrib), rows
    except (ET.ParseError, AttributeError, TypeError, ValueError) as error:
        raise ValidationError(f"Invalid XML: {error}") from error


def write_html(folder, report):
    def esc(value):
        return html.escape(str(value))

    rows = "".join(
        f"<tr><td>{r['year']}</td><td>{r['value']:,}</td></tr>" for r in report.get("rows", [])
    )
    checks = "".join(
        f"<li><b>{esc(c['status'])}</b> — {esc(c['description'])}</li>" for c in report["checks"]
    )
    sources = "".join(
        f"<li><a href='{esc(r['url'])}'>{esc(r['name'])}</a> — {esc(r['status'])}</li>"
        for r in report["fetches"]
    )
    output = f"""<!doctype html><html lang='vi'><meta charset='utf-8'>
<title>Crawl thử đề F</title><style>body{{font:17px/1.65 system-ui;max-width:950px;margin:40px auto;padding:0 24px;color:#172537}}table{{border-collapse:collapse}}td,th{{padding:8px 24px;border:1px solid #ccd5df}}code{{background:#eef2f6}}a{{color:#1659ac}}</style>
<h1>Crawl thử đề F: dân số Việt Nam</h1><p>Trạng thái: <b>{esc(report["status"])}</b></p>
<p>{esc(report["scope"]["description"])}</p><p>Lượt chạy UTC: {esc(report["run_at"])}</p>
<h2>Kết quả kiểm tra</h2><ul>{checks}</ul>
<h2>Dữ liệu</h2><table><tr><th>Năm</th><th>Giá trị dân số</th></tr>{rows}</table>
<p>{esc(report.get("query_example", "Không phát hành dữ liệu khi kiểm tra thất bại."))}</p>
<h2>Nguồn và bản gốc</h2><ul>{sources}</ul>
<h2>Giới hạn kết luận</h2><p>Connector World Bank được chọn trước. Engine tự tìm chỉ số trong danh mục của connector; chưa tự tìm toàn Internet. JSON, XML và bảng DataBank cùng một bộ dữ liệu, không phải ba nguồn độc lập. Kiểm tra chứng minh dữ liệu được tải và đọc đúng theo nguồn này, không chứng minh dân số thực tế chính xác tuyệt đối.</p>
<p>Chưa làm embedding, chatbot, dashboard tương tác hoặc crawler HTML tổng quát. Không dùng hay tiêu budget API BTC.</p>
<p><a href='report.json'>Báo cáo JSON</a> · <a href='fetch-manifest.json'>Manifest và SHA-256</a></p></html>"""
    (folder / "report.html").write_text(output, encoding="utf-8")


def run(config_path, output_root):
    scope = json.loads(config_path.read_text(encoding="utf-8"))
    if scope["provider"] != "worldbank":
        raise ValidationError("Only World Bank connector implemented")
    for key in ("country", "country_iso3", "source_id", "negative_control_country"):
        if not str(scope[key]).isalnum():
            raise ValidationError(f"Invalid scope field: {key}")
    if scope["value_kind"] != "nonnegative_integer":
        raise ValidationError("Only nonnegative integer count policy implemented")
    if not 1900 <= scope["start_year"] <= scope["end_year"] <= 2100:
        raise ValidationError("Invalid year range")
    if Path(scope["scope_id"]).name != scope["scope_id"]:
        raise ValidationError("Invalid scope id")
    now = datetime.now(timezone.utc)
    folder = output_root / scope["scope_id"] / now.strftime("%Y%m%dT%H%M%S%fZ")
    (folder / "raw").mkdir(parents=True)
    fetcher = Fetcher(folder / "raw")
    report = {
        "scope": scope,
        "run_at": now.isoformat(),
        "status": "quarantined",
        "checks": [],
        "fetches": fetcher.manifest,
    }

    def passed(description):
        report["checks"].append({"status": "PASS", "description": description})

    try:
        catalog_url = "https://api.worldbank.org/v2/indicator?" + urllib.parse.urlencode(
            {"source": scope["source_id"], "format": "json", "per_page": 20000}
        )
        indicator, count = discover_indicator(fetcher.fetch(catalog_url, "catalog.json"), scope)
        save_json(
            folder / "discovery.json",
            {
                "mode": "provider_catalog_exact_match",
                "provider_selection": "World Bank selected by developer for bounded pilot",
                "catalog_items": count,
                "selected": indicator,
            },
        )
        passed(
            f"Tìm được duy nhất {indicator['id']} trong {count} chỉ số; có định nghĩa và nguồn gốc"
        )
        base = (
            f"https://api.worldbank.org/v2/country/{scope['country']}/indicator/{indicator['id']}"
        )
        params = {
            "source": scope["source_id"],
            "date": f"{scope['start_year']}:{scope['end_year']}",
            "per_page": 100,
        }
        json_url = base + "?" + urllib.parse.urlencode({**params, "format": "json"})
        time.sleep(0.5)
        meta, raw_rows = unpack_json(fetcher.fetch(json_url, "observations.json"))
        rows = validate_rows(meta, raw_rows, scope, indicator["id"])
        passed(
            f"Đúng quốc gia/chỉ số/dataset; đủ {len(rows)} năm; không trùng, thiếu hoặc giá trị lỗi"
        )
        time.sleep(0.5)
        xml_meta, xml_rows = unpack_xml(
            fetcher.fetch(base + "?" + urllib.parse.urlencode(params), "observations.xml")
        )
        xml_clean = validate_rows(xml_meta, xml_rows, scope, indicator["id"])
        if [(r["year"], r["value"]) for r in rows] != [
            (r["year"], r["value"]) for r in xml_clean
        ] or meta["lastupdated"] != xml_meta["lastupdated"]:
            raise ValidationError("JSON/XML values or dataset versions disagree")
        passed("Hai đường parse JSON và XML khớp từng năm, từng giá trị và phiên bản dataset")
        benchmark_path = (config_path.parent / scope["benchmark"]).resolve()
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        if (
            benchmark["country_iso3"] != scope["country_iso3"]
            or benchmark["indicator_id"] != indicator["id"]
            or benchmark["source_id"] != scope["source_id"]
            or {str(r["year"]): r["value"] for r in rows} != benchmark["values"]
        ):
            raise ValidationError(
                "Does not match scoped DataBank benchmark; review source revisions"
            )
        save_json(folder / "benchmark-used.json", benchmark)
        passed("5/5 giá trị khớp bảng DataBank đã đối chiếu trong phiên này")
        control_url = json_url.replace(
            f"/country/{scope['country']}/", f"/country/{scope['negative_control_country']}/"
        )
        time.sleep(0.5)
        control_meta, control_rows = unpack_json(
            fetcher.fetch(control_url, "negative-control.json")
        )
        try:
            validate_rows(control_meta, control_rows, scope, indicator["id"])
        except ValidationError as error:
            if str(error) != "Wrong country":
                raise
            passed("Chặn thành công dữ liệu Mỹ tải thật vì sai quốc gia của scope")
        else:
            raise ValidationError("Negative control incorrectly accepted")
        for row in rows:
            row.update(
                {
                    "source_url": json_url,
                    "raw_path": "raw/observations.json",
                    "raw_sha256": fetcher.manifest[1]["sha256"],
                    "dataset_last_updated": meta["lastupdated"],
                }
            )
        save_json(folder / "accepted.json", rows)
        with (folder / "accepted.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with closing(sqlite3.connect(folder / "accepted.sqlite")) as connection, connection:
            connection.execute(
                "CREATE TABLE observations(country TEXT, year INTEGER, indicator TEXT, value INTEGER, source_url TEXT, raw_locator TEXT, PRIMARY KEY(country, year, indicator))"
            )
            connection.executemany(
                "INSERT INTO observations VALUES(?,?,?,?,?,?)",
                [
                    (
                        r["country"],
                        r["year"],
                        r["indicator"],
                        r["value"],
                        r["source_url"],
                        r["raw_locator"],
                    )
                    for r in rows
                ],
            )
            difference = connection.execute(
                "SELECT (SELECT value FROM observations WHERE year=?) - (SELECT value FROM observations WHERE year=?)",
                (scope["end_year"], scope["start_year"]),
            ).fetchone()[0]
        report.update(
            {
                "status": "accepted",
                "rows": rows,
                "query_example": f"SQL thử: dân số {scope['end_year']} tăng {difference:,} người so với {scope['start_year']}.",
                "indicator_metadata": indicator,
            }
        )
    except Exception as error:
        # Partial persistence must never leave accepted outputs after a failed run.
        for filename in ("accepted.json", "accepted.csv", "accepted.sqlite"):
            (folder / filename).unlink(missing_ok=True)
        report["error"] = str(error)
        report["checks"].append({"status": "FAIL", "description": str(error)})
    finally:
        save_json(folder / "fetch-manifest.json", fetcher.manifest)
        save_json(folder / "report.json", report)
        write_html(folder, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(folder / "report.html"),
                "checks": report["checks"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "runs")
    args = parser.parse_args()
    raise SystemExit(run(args.scope.resolve(), args.output.resolve()))
