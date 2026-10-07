"""Fixed AI destinations; no credential-bearing redirects or proxy inheritance."""

import json
import urllib.error
import urllib.request


class NoAIRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("AI redirect blocked; credentials must stay at configured provider")


AI_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoAIRedirect())


def post(url, body, key, timeout=45, max_bytes=4_000_000):
    if url not in (
        "https://api.openai.com/v1/responses",
        "https://api.openai.com/v1/embeddings",
        "https://api.thucchien.ai/responses",
        "https://api.thucchien.ai/embeddings",
    ):
        raise ValueError("AI destination outside allowlist")
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with AI_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as error:
        # Provider response bodies/headers can contain confidential request information.
        raise ValueError(f"AI_HTTP_{error.code}: request failed; provider body omitted") from None
    except urllib.error.URLError:
        raise ValueError("AI_NETWORK_ERROR: request failed") from None
    if len(raw) > max_bytes:
        raise ValueError("AI response exceeds size limit")
    return raw
