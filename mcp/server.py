#!/usr/bin/env python3
"""uwae MCP server — stdlib only, zero dependencies.

Exposes one tool over stdio (newline-delimited JSON-RPC 2.0, MCP protocol):
  fetch_url(url, max_bytes?) -> page content as clean markdown.

Run:  python3 mcp/server.py
"""

import json
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser

SERVER_INFO = {"name": "uwae", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_MAX_BYTES = 200_000
TIMEOUT_SECONDS = 15
USER_AGENT = "uwae-mcp/0.1 (+https://github.com/username9999-sys/uwae)"

TOOLS = [
    {
        "name": "fetch_url",
        "description": (
            "Fetch a URL and return its content as clean markdown (HTML pages) "
            "or plain text (everything else). Use this instead of reading raw "
            "HTML so web content costs hundreds of tokens, not tens of thousands."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http(s) URL to fetch"},
                "max_bytes": {
                    "type": "integer",
                    "description": "Max response bytes to read",
                    "default": DEFAULT_MAX_BYTES,
                },
            },
            "required": ["url"],
        },
    }
]

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})
_HEADING_TAGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}


class _Markdowner(HTMLParser):
    """Minimal HTML -> markdown converter (stdlib html.parser)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0
        self._pre_depth = 0
        self._link: list[str] | None = None
        self._buf = ""

    def _flush(self) -> None:
        text = " ".join(self._buf.split())
        if text:
            self._out.append(text)
        self._buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            self._flush()
            self._out.append("\n" + _HEADING_TAGS[tag])
        elif tag == "p":
            self._flush()
            self._out.append("\n\n")
        elif tag == "br":
            self._flush()
            self._out.append("\n")
        elif tag == "li":
            self._flush()
            self._out.append("\n- ")
        elif tag == "pre":
            self._flush()
            self._pre_depth += 1
            self._out.append("\n```\n")
        elif tag == "a":
            self._flush()
            href = next((v for k, v in attrs if k == "href" and v), "")
            self._link = ["", href]
        elif tag == "img":
            alt = next((v for k, v in attrs if k == "alt" and v), "")
            if alt:
                self._buf += f" {alt} "

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS:
            self._flush()
            self._out.append("\n\n")
        elif tag == "p":
            self._flush()
            self._out.append("\n\n")
        elif tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
            self._flush()
            self._out.append("\n```\n\n")
        elif tag == "a" and self._link is not None:
            text, href = self._link
            text = " ".join(text.split())
            self._buf += f"[{text}]({href})" if text and href else (text or href)
            self._link = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._link is not None:
            self._link[0] += data
        else:
            self._buf += data

    def markdown(self) -> str:
        self._flush()
        out = "".join(self._out)
        lines = [ln.rstrip() for ln in out.splitlines()]
        return "\n".join(lines).strip() + "\n"


def html_to_markdown(html: str) -> str:
    parser = _Markdowner()
    parser.feed(html)
    parser.close()
    return parser.markdown()


def fetch_url(url: str, max_bytes: int = DEFAULT_MAX_BYTES) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            status = resp.status
            final_url = resp.geturl()
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        return {
            "content": [{"type": "text", "text": f"HTTP {e.code} for {url}: {e.reason}"}],
            "isError": True,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {
            "content": [{"type": "text", "text": f"fetch failed for {url}: {e}"}],
            "isError": True,
        }
    truncated = len(body) > max_bytes
    text = body[:max_bytes].decode("utf-8", errors="replace")
    markdown = html_to_markdown(text) if "html" in content_type.lower() else text
    payload = {
        "url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "bytes": len(body),
        "truncated": truncated,
        "markdown": markdown,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def handle_message(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        if params.get("name") == "fetch_url":
            args = params.get("arguments", {})
            result = fetch_url(args.get("url", ""), int(args.get("max_bytes", DEFAULT_MAX_BYTES)))
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": f"unknown tool: {params.get('name')}"}], "isError": True},
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if msg_id is not None:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_message(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
