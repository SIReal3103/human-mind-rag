#!/usr/bin/env python3
import io
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ingestion


class LocalIngestionTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"DOCUMENT_PARSER": "native"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_upstream_commit_is_available(self):
        info = ingestion.upstream_info()
        self.assertTrue(info["available"], info)
        self.assertEqual(info["commit"], ingestion.UPSTREAM_COMMIT)
        self.assertEqual(info["parser_mode"], "native")

    def test_real_unicode_text_and_reviewed_chunks(self):
        text = "Phạm vi tài liệu cần người duyệt kiểm tra. Dữ liệu gốc giữ nguyên.\n" * 90
        parsed = ingestion.extract(text.encode(), "text/plain", "ghi-chu.txt")
        self.assertEqual(parsed["text"], text)
        self.assertFalse(parsed["partial"])
        chunks = ingestion.make_chunks(parsed["text"])
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunk["text"] for chunk in chunks), text)
        for chunk in chunks:
            self.assertLessEqual(chunk["tokens"], 400)
            locator = chunk["locator"]
            self.assertEqual(locator["kind"], "reviewed_text")
            self.assertNotIn("page", locator)
            self.assertEqual(chunk["text"], text[locator["start"] : locator["end"]])

    def test_real_html_extraction(self):
        sentence = "Tài liệu hướng dẫn kiểm tra nguồn gốc dữ liệu trước khi đưa vào kho tri thức. "
        html = (
            "<html><head><title>Hướng dẫn nguồn</title></head><body><article>"
            "<h1>Hướng dẫn nguồn</h1><p>" + sentence * 12 + "</p></article></body></html>"
        )
        parsed = ingestion.extract(html.encode(), "text/html; charset=utf-8", "huong-dan.html")
        self.assertIn(sentence.strip(), parsed["text"])
        self.assertEqual(parsed["parser"], "trafilatura+html-tables-v2")
        self.assertNotIn("<article>", parsed["text"])

    def test_real_pdf_preserves_source_page_locators(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = PdfWriter()
        for number in (1, 2):
            page = writer.add_blank_page(width=612, height=792)
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            sentence = f"Page {number} source evidence needs human review. " * 7
            stream = DecodedStreamObject()
            stream.set_data(("BT /F1 12 Tf 20 750 Td (" + sentence + ") Tj ET").encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        parsed = ingestion.extract(output.getvalue(), "application/pdf", "source.pdf")
        self.assertEqual([segment["locator"]["page"] for segment in parsed["segments"]], [1, 2])
        self.assertTrue(any("no OCR" in warning for warning in parsed["warnings"]))
        chunks = ingestion.make_chunks(parsed["text"], parsed["segments"])
        for chunk in chunks:
            locator = chunk["locator"]
            source = parsed["segments"][locator["page"] - 1]["text"]
            self.assertEqual(chunk["text"], source[locator["start"] : locator["end"]])
        self.assertEqual({chunk["locator"]["page"] for chunk in chunks}, {1, 2})

    def test_mixed_pdf_reports_image_only_page_but_not_blank_page(self):
        from PIL import Image, ImageDraw
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        document = canvas.Canvas(output)
        for line in range(8):
            document.drawString(40, 750 - 20 * line, "Text cover: original evidence needs review.")
        document.showPage()
        image = Image.new("RGB", (400, 200), "white")
        ImageDraw.Draw(image).text((20, 80), "Scanned source: amount 12345", fill="black")
        document.drawImage(ImageReader(image), 40, 450, width=400, height=200)
        document.showPage()
        document.showPage()
        document.save()

        parsed = ingestion.extract(output.getvalue(), "application/pdf", "mixed-source.pdf")
        self.assertTrue(parsed["partial"])
        self.assertEqual([segment["locator"]["page"] for segment in parsed["segments"]], [1])
        coverage_warning = next(warning for warning in parsed["warnings"] if "Trang PDF" in warning)
        self.assertIn("Trang PDF 2:", coverage_warning)
        self.assertIn("OCR", coverage_warning)
        self.assertNotIn("3", coverage_warning)

    def test_native_pdf_with_blank_page_does_not_claim_missing_content(self):
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        document = canvas.Canvas(output)
        for line in range(8):
            document.drawString(40, 750 - 20 * line, "Text source: original evidence needs review.")
        document.showPage()
        document.showPage()
        document.save()

        parsed = ingestion.extract(output.getvalue(), "application/pdf", "blank-page.pdf")
        self.assertFalse(parsed["partial"])
        self.assertFalse(any("Trang PDF" in warning for warning in parsed["warnings"]))

    def test_changed_text_cannot_keep_old_source_locations(self):
        with self.assertRaisesRegex(ValueError, "không khớp"):
            ingestion.make_chunks(
                "Edited content", [{"text": "Original content", "locator": {"page": 3}}]
            )

    def test_missing_engine_and_invalid_input_fail_explicitly(self):
        with patch("ingestion.upstream_info", return_value={"available": False}):
            with self.assertRaisesRegex(ValueError, "engine"):
                ingestion.extract(b"A document", "text/plain", "source.txt")
        for body in (b"", b"x" * (ingestion.MAX_BYTES + 1)):
            with self.assertRaises(ValueError):
                ingestion.extract(body, "text/plain", "source.txt")

    def test_worker_does_not_inherit_credentials_or_proxy(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "parent-secret",
                "BTC_API_KEY": "parent-secret",
                "HTTPS_PROXY": "http://proxy.invalid",
                "PYTHONPATH": "/untrusted",
                "UNRELATED_SECRET": "parent-secret",
            },
        ):
            environment = ingestion._worker_environment()
        self.assertEqual(environment["AI_PROVIDER"], "btc")
        self.assertEqual(environment["OPENAI_API_KEY"], "")
        self.assertEqual(environment["BTC_API_KEY"], "")
        for name in ("HTTPS_PROXY", "PYTHONPATH", "UNRELATED_SECRET"):
            self.assertNotIn(name, environment)


class PublicFetchTests(unittest.TestCase):
    def test_fetch_worker_reports_network_failure_without_internal_details(self):
        detail = "internal network diagnostic with private path /tmp/worker-source"
        failures = (
            (socket.timeout(detail), "vượt thời gian"),
            (ssl.SSLCertVerificationError(detail), "chứng chỉ HTTPS"),
            (ssl.SSLError(detail), "HTTPS an toàn"),
            (ConnectionRefusedError(detail), "Kết nối tới nguồn"),
            (http.client.RemoteDisconnected(detail), "Kết nối tới nguồn"),
        )
        with tempfile.TemporaryDirectory(prefix="fetch-worker-test-") as folder:
            request = Path(folder) / "request.json"
            response = Path(folder) / "response.json"
            request.write_text(json.dumps({"url": "https://example.com/source"}))
            for failure, message in failures:
                with (
                    self.subTest(failure=type(failure).__name__),
                    patch.object(
                        sys, "argv", ["ingestion.py", "--fetch-worker", str(request), str(response)]
                    ),
                    patch("ingestion._fetch_local", side_effect=failure),
                ):
                    ingestion._main()
                    record = json.loads(response.read_text())
                    self.assertEqual(set(record), {"error"})
                    self.assertIn(message, record["error"])
                    self.assertNotIn(detail, record["error"])
                    self.assertNotIn("parser", record["error"])

    def test_worker_timeout_distinguishes_fetch_from_parser(self):
        for operation, message in (
            ("--fetch-worker", "Tải nguồn vượt thời gian"),
            ("--parse-worker", "Tác vụ xử lý vượt thời gian"),
        ):
            process = MagicMock()
            process.wait.side_effect = [ingestion.subprocess.TimeoutExpired(operation, 1), 0]
            with (
                self.subTest(operation=operation),
                patch("ingestion.subprocess.Popen", return_value=process),
                patch("ingestion.os.killpg"),
                self.assertRaisesRegex(ValueError, message),
            ):
                ingestion._run_worker(operation, {}, 1)
            self.assertEqual(process.wait.call_count, 2)

    def test_url_rejects_credentials_schemes_and_nonstandard_ports(self):
        for url in (
            "file:///etc/passwd",
            "http://user:pass@example.com",
            "http://example.com:8080",
            "https://example.com:80",
            "https://example.com/\r\nX:1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ingestion.fetch_public(url)

    def test_local_loopback_fetch_is_blocked_in_real_worker(self):
        with self.assertRaisesRegex(ValueError, "nội bộ|không công khai"):
            ingestion.fetch_public("http://127.0.0.1/")

    def test_dns_rejects_private_multicast_and_mixed_results(self):
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "224.0.0.1", "100.64.0.1"):
            private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))
            with (
                self.subTest(address=address),
                patch("socket.getaddrinfo", return_value=[public, private]),
            ):
                with self.assertRaises(ValueError):
                    ingestion._resolve_public("example.com", 80)

    def test_redirect_resolves_and_rechecks_destination(self):
        response = MagicMock(status=302)
        response.getheader.side_effect = lambda name, default=None: (
            "http://127.0.0.1/" if name == "Location" else default
        )
        connection = MagicMock()
        connection.getresponse.return_value = response
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        with patch("socket.getaddrinfo", side_effect=[[public], [private]]) as resolver:
            with patch("ingestion._pinned_connection", return_value=connection) as connect:
                with self.assertRaises(ValueError):
                    ingestion._fetch_local("http://example.com/")
        self.assertEqual(resolver.call_count, 2)
        self.assertEqual(connect.call_count, 1)
        connection.close.assert_called_once()

    def test_connection_uses_validated_ip_and_original_tls_hostname(self):
        address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        raw_socket = MagicMock()
        tls_context = MagicMock()
        with (
            patch("socket.socket", return_value=raw_socket),
            patch("ssl.create_default_context", return_value=tls_context),
        ):
            with patch("socket.getaddrinfo", side_effect=AssertionError("DNS must not repeat")):
                connection = ingestion._pinned_connection(
                    urlsplit("https://example.com/a"), "example.com", 443, address, 3
                )
        raw_socket.connect.assert_called_once_with(("93.184.216.34", 443))
        tls_context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="example.com")
        self.assertIs(connection.sock, tls_context.wrap_socket.return_value)

    def test_declared_and_actual_size_are_bounded(self):
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        for declared in (str(ingestion.MAX_BYTES + 1), None):
            response = MagicMock(status=200)
            response.getheader.side_effect = lambda name, default=None, declared=declared: (
                declared if name == "Content-Length" else default
            )
            response.read.return_value = b"x" * (ingestion.MAX_BYTES + 1)
            connection = MagicMock()
            connection.getresponse.return_value = response
            with (
                patch("ingestion._resolve_public", return_value=public),
                patch("ingestion._pinned_connection", return_value=connection),
            ):
                with self.assertRaisesRegex(ValueError, "10 MB"):
                    ingestion._fetch_local("http://example.com/")


if __name__ == "__main__":
    unittest.main()
