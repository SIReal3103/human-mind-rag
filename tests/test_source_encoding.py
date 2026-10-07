"""Real compressed input verifies limits without network or provider calls."""

import gzip

import pytest

from ingestion import decode_source_body


def test_gzip_and_identity_return_original_source():
    text = ("Nội dung báo cáo nguồn công khai.\n" * 20).encode()
    for encoding in ("gzip", "GZip", "x-gzip"):
        assert decode_source_body(gzip.compress(text), encoding, len(text)) == text
    assert decode_source_body(text, None, len(text)) == text
    assert decode_source_body(text, "identity", len(text)) == text


def test_compressed_and_decoded_sizes_are_bounded():
    with pytest.raises(ValueError, match="dung lượng tải"):
        decode_source_body(b"plain source", "identity", 4)
    compressed = gzip.compress(b"x" * 10000)
    with pytest.raises(ValueError, match="sau giải nén"):
        decode_source_body(compressed, "gzip", 100)
    # Every member counts towards the same decoded size limit.
    joined = gzip.compress(b"a" * 80) + gzip.compress(b"b" * 80)
    assert decode_source_body(joined, "gzip", 160) == b"a" * 80 + b"b" * 80
    with pytest.raises(ValueError, match="sau giải nén"):
        decode_source_body(joined, "gzip", 100)


def test_truncated_corrupt_and_unknown_encodings_are_rejected():
    valid = gzip.compress(b"source")
    for broken in (valid[:-4], b"not gzip", valid[:-8] + b"\x00" * 8):
        with pytest.raises(ValueError, match="gzip"):
            decode_source_body(broken, "gzip", 1000)
    with pytest.raises(ValueError, match="chưa được hỗ trợ"):
        decode_source_body(valid, "gzip, br", 1000)
