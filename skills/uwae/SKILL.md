---
name: uwae
description: "Fetch any web page and return it as clean, token-efficient markdown for the agent. Use whenever the user asks to read a URL, scrape a page, summarize a website, check what a link contains, or feed web content into analysis. Trigger phrases: fetch this url, what does this page say, scrape, get the content of, read this link, website to markdown."
license: MIT
compatibility: Works in Claude Code, Codex, OpenCode, Antigravity, MiniMax Code. No API key needed. Rust binary is the fast path; the bundled stdlib MCP server is the zero-dependency fallback.
metadata:
  opencode/slash: "true"
---

# uwae — web → markdown for agents

Turn any URL into clean markdown so the agent reads hundreds of tokens, not tens of thousands of HTML.

## How to fetch

Pick the first available path, in order:

1. **Rust binary (fastest):** `uwae-fetch <url>` → markdown on stdout. `--json` for `{url, final_url, status, title, markdown, bytes}`. Binary at `fetcher/target/release/uwae-fetch` in this repo, or install with `cargo install --git https://github.com/username9999-sys/uwae --root ~/.cargo uwae-fetch`.
2. **MCP server (zero Python dependencies):** `mcp/server.py` in this repo exposes one tool, `fetch_url(url, max_bytes?)`. Register it in the harness MCP config (see README) and call `fetch_url`.
3. **Python engine (full pipeline):** `uwae acquire <url> --json` — artifact-first, retry budget, failure isolation. Install with `pip install -e .` from this repo.

## Rules

- Always report `final_url` and HTTP `status` alongside the content — redirects and soft-404s are common.
- Never paste raw HTML into the answer; return the markdown.
- If the page needs JavaScript rendering or login, say so explicitly and use the Python engine's `--browser` / `--session-login` flags instead of pretending the fetch worked.
- Respect robots.txt for crawls; for a single user-requested URL, one fetch is fine.
