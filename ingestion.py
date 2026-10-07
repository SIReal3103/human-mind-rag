#!/usr/bin/env python3
"""Local, process-isolated reuse of the pinned external scope-data-bot checkout."""

from __future__ import annotations

import base64
import gzip
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import zlib
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import certifi


UPSTREAM_COMMIT = "cb37446a00c6283cbb596df524885cfcb08a9fe7"
MAX_BYTES = 10_000_000
MAX_TEXT = 600_000
MAX_RESULT = 20_000_000
FETCH_TIMEOUT = 30
CHUNK_TOKENS = 400


def decode_source_body(body, encoding, limit):
    """Bound both wire bytes and decoded content, including concatenated gzip members."""
    if len(body) > limit:
        raise ValueError("Nguồn vượt giới hạn dung lượng tải.")
    encoding = (encoding or "identity").strip().lower()
    if encoding == "identity":
        return body
    if encoding not in ("gzip", "x-gzip"):
        raise ValueError("Định dạng nén nguồn chưa được hỗ trợ; cần identity hoặc gzip.")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            decoded = stream.read(limit + 1)
    except (OSError, EOFError, zlib.error):
        raise ValueError("Nội dung gzip của nguồn không hợp lệ hoặc tải chưa đầy đủ.") from None
    if len(decoded) > limit:
        raise ValueError("Nguồn sau giải nén vượt giới hạn dung lượng.")
    return decoded


def _upstream_path():
    default = Path(__file__).resolve().parent / ".runtime" / "scope-data-bot"
    return Path(os.environ.get("SCOPE_BOT_PATH", str(default))).expanduser().resolve()


def upstream_info():
    path = _upstream_path()
    commit = None
    pristine = False
    if path.is_dir():
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                commit = result.stdout.strip()
                pristine = (
                    subprocess.run(
                        ["git", "-C", str(path), "diff", "--quiet", "HEAD", "--"],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    ).returncode
                    == 0
                )
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "available": commit == UPSTREAM_COMMIT
        and pristine
        and all((path / name).is_file() for name in ("bot.py", "data_pipeline.py")),
        "commit": commit,
        "pristine": pristine,
        "path": str(path),
        "parser_mode": os.environ.get("DOCUMENT_PARSER", "native"),
    }


def _require_upstream():
    info = upstream_info()
    if not info["available"]:
        raise ValueError(
            "Cần checkout scope-data-bot nguyên bản tại SCOPE_BOT_PATH, không sửa tệp tracked, commit "
            + UPSTREAM_COMMIT
        )
    return info


def _worker_environment():
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(
        {
            "SCOPE_BOT_PATH": str(_upstream_path()),
            "SSL_CERT_FILE": certifi.where(),
            "AI_PROVIDER": "btc",
            "BTC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "THUCCHIEN_API_KEY": "",
            "BTC_STRUCTURED_VERIFIED": os.environ.get("BTC_STRUCTURED_VERIFIED", "0"),
            "BTC_SEARCH_VERIFIED": os.environ.get("BTC_SEARCH_VERIFIED", "0"),
            "BTC_EMBEDDING_VERIFIED": os.environ.get("BTC_EMBEDDING_VERIFIED", "0"),
            "BTC_EMBEDDING_BATCH_VERIFIED": os.environ.get("BTC_EMBEDDING_BATCH_VERIFIED", "0"),
            "DOCUMENT_PARSER": os.environ.get("DOCUMENT_PARSER", "native"),
            "DOCUMENT_OCR": os.environ.get("DOCUMENT_OCR", "auto"),
            "DOCUMENT_OCR_LANGUAGES": os.environ.get("DOCUMENT_OCR_LANGUAGES", "vi,en"),
            "DOCUMENT_MAX_PAGES": os.environ.get("DOCUMENT_MAX_PAGES", "40"),
            "DOCUMENT_TIMEOUT": "180",
            "DOCUMENT_THREADS": "2",
            "DOCLING_PYTHON": os.environ.get(
                "DOCLING_PYTHON", str(_upstream_path() / ".venv-docling/bin/python")
            ),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    if "TIKTOKEN_CACHE_DIR" in os.environ:
        env["TIKTOKEN_CACHE_DIR"] = os.environ["TIKTOKEN_CACHE_DIR"]
    return env


def _run_worker(operation, payload, timeout):
    with tempfile.TemporaryDirectory(prefix="rag-review-") as temporary:
        request_path = Path(temporary) / "request.json"
        response_path = Path(temporary) / "response.json"
        request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-I",
                    str(Path(__file__).resolve()),
                    operation,
                    str(request_path),
                    str(response_path),
                ],
                env=_worker_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                process.wait(timeout=timeout)
            except BaseException:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                process.wait()
                raise
        except subprocess.TimeoutExpired:
            raise ValueError("Tác vụ xử lý vượt thời gian cho phép.") from None
        except OSError:
            raise ValueError("Không khởi chạy được trình xử lý cục bộ.") from None
        if process.returncode or not response_path.is_file():
            raise ValueError("Trình xử lý cục bộ không hoàn tất.")
        if response_path.stat().st_size > MAX_RESULT:
            raise ValueError("Kết quả xử lý vượt giới hạn dung lượng.")
        try:
            result = json.loads(response_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise ValueError("Kết quả xử lý không hợp lệ.") from None
        if "error" in result:
            raise ValueError(result["error"])
        return result["result"]


def extract(body: bytes, mime: str, filename: str) -> dict:
    if not isinstance(body, bytes) or not body or len(body) > MAX_BYTES:
        raise ValueError("Tài liệu phải có nội dung và không vượt 10 MB.")
    mode = _require_upstream()["parser_mode"]
    if mode not in ("native", "docling"):
        raise ValueError("DOCUMENT_PARSER phải là native hoặc docling.")
    return _run_worker(
        "--parse-worker",
        {"body": base64.b64encode(body).decode("ascii"), "mime": mime, "filename": filename},
        190 if mode == "docling" else 60,
    )


def _extract_local(payload):
    info = _require_upstream()
    sys.path.insert(0, info["path"])
    from bot import extract_document

    body = base64.b64decode(payload["body"], validate=True)
    mime = payload["mime"].split(";", 1)[0].strip().lower()
    filename = Path(payload["filename"]).name
    if mime in ("text/plain", "text/markdown") and not body.startswith(b"%PDF-"):
        try:
            document = {"text": body.decode("utf-8-sig"), "parser": "utf8-text"}
        except UnicodeDecodeError:
            raise ValueError("Tệp văn bản phải dùng mã UTF-8.") from None
    else:
        document = extract_document(
            body, mime, "utf-8", "https://uploaded.invalid/" + quote(filename), scope=None
        )
    text = document.get("text", "")
    if not text.strip() or len(text) > MAX_TEXT:
        raise ValueError("Không trích được văn bản hoặc văn bản vượt 600.000 ký tự.")
    segments = [
        {"text": page["text"], "locator": {"kind": "page", "page": page["page"]}}
        for page in document.get("pages", [])
        if page.get("text")
    ]
    if not segments:
        segments = [{"text": text, "locator": {"kind": "document_text"}}]
    warnings = list(document.get("parse_warnings", []))
    missing_pages = []
    if document["parser"].startswith("pypdf-"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        if len(reader.pages) > 500:
            raise ValueError("PDF vượt giới hạn 500 trang để kiểm tra độ phủ.")
        page_text = {page["page"]: page["text"] for page in document.get("pages", [])}
        for number, page in enumerate(reader.pages, 1):
            # Empty pages are not missing evidence unless they contain image content.
            # This detects whole image-only pages, not every omitted figure or OCR error.
            if not page_text.get(number, "").strip() and page.images.keys():
                missing_pages.append(number)
        if missing_pages:
            warnings.append(
                "Trang PDF "
                + ", ".join(map(str, missing_pages))
                + ": có ảnh nhưng không trích được chữ. Bản trích chưa đầy đủ; cần OCR "
                "hoặc nhập lại nguồn văn bản đầy đủ đã đối chiếu. Kiểm tra này không "
                "phát hiện mọi nội dung trong ảnh hoặc thiếu sót OCR."
            )
    if document.get("coverage_note"):
        warnings.append(document["coverage_note"])
    for table in document.get("tables", []):
        for warning in table.get("warnings", []):
            warnings.append(warning.get("message") or warning.get("code", "Kiểm tra lại bảng."))
    return {
        "text": text,
        "parser": document["parser"],
        "segments": segments,
        "warnings": warnings,
        "partial": bool(document.get("parse_partial", False) or missing_pages),
    }


def make_chunks(text: str, segments: list[dict] | None = None) -> list[dict]:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError("Văn bản trống hoặc vượt giới hạn xử lý.")
    _require_upstream()
    return _run_worker("--chunk-worker", {"text": text, "segments": segments}, 60)


def _chunks_local(payload):
    info = _require_upstream()
    sys.path.insert(0, info["path"])
    from data_pipeline import spans, tokens

    text, segments = payload["text"], payload.get("segments")
    if segments is None:
        segments = [{"text": text, "locator": {"kind": "reviewed_text"}}]
    if not isinstance(segments, list) or not segments:
        raise ValueError("Danh sách đoạn nguồn không hợp lệ.")
    chunks, position = [], 0
    for segment in segments:
        content, locator = segment.get("text"), segment.get("locator")
        if not isinstance(content, str) or not isinstance(locator, dict):
            raise ValueError("Đoạn nguồn thiếu văn bản hoặc vị trí.")  # noqa: TRY004 - public adapter contract
        if not content:
            continue
        source_start = text.find(content, position)
        if source_start < 0 or text[position:source_start].strip():
            raise ValueError("Đoạn nguồn không khớp văn bản; cần bỏ vị trí cũ sau khi chỉnh sửa.")
        for start, end in spans(content, CHUNK_TOKENS):
            value = content[start:end]
            location = {**locator, "start": start, "end": end}
            chunk_id = hashlib.sha256(
                json.dumps(
                    [len(chunks), location, value], sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()[:24]
            chunks.append(
                {"id": "c" + chunk_id, "text": value, "locator": location, "tokens": tokens(value)}
            )
        position = source_start + len(content)
    if text[position:].strip() or not chunks:
        raise ValueError("Đoạn nguồn không bao phủ hết văn bản.")
    return chunks


def _public_target(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Chỉ chấp nhận URL HTTP hoặc HTTPS công khai.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL không được chứa thông tin đăng nhập.")
        default_port = 443 if parsed.scheme == "https" else 80
        if parsed.port not in (None, default_port):
            raise ValueError("Chỉ chấp nhận cổng mặc định 80/443.")
        hostname = parsed.hostname.encode("idna").decode("ascii")
        if any(ord(char) < 33 for char in url) or "\\" in url:
            raise ValueError("URL có ký tự không hợp lệ.")
        return parsed, hostname, default_port
    except (UnicodeError, ValueError) as error:
        raise ValueError(str(error)) from None


def _resolve_public(hostname, port):
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("Không phân giải được tên miền nguồn.") from None
    if not addresses:
        raise ValueError("Nguồn không có địa chỉ mạng công khai.")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0].split("%", 1)[0])
        effective = (
            ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip
        )
        if not effective.is_global or effective.is_multicast:
            raise ValueError("Chặn địa chỉ mạng nội bộ hoặc không công khai.")
    return addresses[0]


def _pinned_connection(parsed, hostname, port, address, timeout):
    family, kind, protocol, _, sockaddr = address
    connection = http.client.HTTPConnection(hostname, port, timeout=timeout)
    raw_socket = socket.socket(family, kind, protocol)
    try:
        raw_socket.settimeout(timeout)
        raw_socket.connect(sockaddr)
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            context.load_verify_locations(cafile=certifi.where())
            connection.sock = context.wrap_socket(raw_socket, server_hostname=hostname)
        else:
            connection.sock = raw_socket
    except BaseException:
        raw_socket.close()
        raise
    return connection


def _fetch_local(url):
    deadline = time.monotonic() + FETCH_TIMEOUT
    for _ in range(6):
        parsed, hostname, port = _public_target(url)
        address = _resolve_public(hostname, port)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Tải nguồn vượt thời gian cho phép.")
        connection = _pinned_connection(parsed, hostname, port, address, remaining)
        try:
            target = urlunsplit(
                (
                    "",
                    "",
                    quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                    quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~"),
                    "",
                )
            )
            connection.request(
                "GET",
                target,
                headers={
                    "User-Agent": "RagDocumentReview/1.0",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Nguồn chuyển hướng thiếu địa chỉ đích.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("Nguồn trả HTTP " + str(response.status) + ".")
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_BYTES):
                raise ValueError("Nguồn vượt 10 MB hoặc có dung lượng không hợp lệ.")
            parts, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Tải nguồn vượt thời gian cho phép.")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                part = response.read(min(65_536, MAX_BYTES + 1 - size))
                if not part:
                    break
                size += len(part)
                if size > MAX_BYTES:
                    raise ValueError("Nguồn vượt 10 MB.")
                parts.append(part)
            body = decode_source_body(
                b"".join(parts), response.getheader("Content-Encoding"), MAX_BYTES
            )
            if not body:
                raise ValueError("Nguồn không có nội dung.")
            return body, response.getheader("Content-Type", "application/octet-stream"), url
        finally:
            connection.close()
    raise ValueError("Nguồn chuyển hướng quá nhiều lần.")


def fetch_public(url: str) -> tuple[bytes, str, str]:
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("URL không hợp lệ hoặc quá dài.")
    _public_target(url)
    result = _run_worker("--fetch-worker", {"url": url}, FETCH_TIMEOUT + 2)
    return base64.b64decode(result["body"]), result["mime"], result["url"]


def _main():
    operation, request_path, response_path = sys.argv[1:]
    try:
        payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
        if operation == "--parse-worker":
            result = _extract_local(payload)
        elif operation == "--chunk-worker":
            result = _chunks_local(payload)
        elif operation == "--fetch-worker":
            body, mime, url = _fetch_local(payload["url"])
            result = {"body": base64.b64encode(body).decode("ascii"), "mime": mime, "url": url}
        else:
            raise ValueError("Tác vụ không được hỗ trợ.")
        record = {"result": result}
    except ModuleNotFoundError:
        record = {
            "error": "Thiếu thư viện xử lý; cài requirements.txt và runtime parser tương ứng."
        }
    except ValueError as error:
        record = {"error": str(error)[:1000]}
    except Exception:  # noqa: BLE001 - RPC boundary deliberately hides dependency stack traces
        record = {"error": "Không xử lý được nguồn; kiểm tra định dạng và runtime parser."}
    Path(response_path).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    _main()
