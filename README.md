# uwae — web → markdown for AI agents

<p align="center">
  <a href="https://github.com/username9999-sys/uwae"><img src="https://img.shields.io/badge/Rust-fast_path-crab?style=flat-square&logo=rust" alt="Rust"></a>
  <a href="skills/uwae/SKILL.md"><img src="https://img.shields.io/badge/Agent_Skill-compatible-1b1b19?style=flat-square" alt="Agent Skills compatible"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2e7d32.svg?style=flat-square" alt="MIT license"></a>
  <a href="mcp/server.py"><img src="https://img.shields.io/badge/MCP_server-0_python_deps-1b1b19?style=flat-square" alt="Zero-dependency MCP server"></a>
  <a href="fetcher/Cargo.toml"><img src="https://img.shields.io/badge/binary-1_file_6MB-1b1b19?style=flat-square" alt="Single 6MB binary"></a>
</p>

Fetch any URL and get **clean markdown** — hundreds of tokens instead of tens of thousands of raw HTML. Built for coding agents that need to read the web.

```sh
# one line, no install
npx skills add username9999-sys/uwae --skill uwae -g
```

Then in your agent: *"what does https://example.com say?"* — the agent fetches it as markdown.

## Three ways to fetch

| Path | Command | When |
|---|---|---|
| **Rust binary** (fastest) | `uwae-fetch <url> [--json]` | always, if you have cargo |
| **MCP server** (0 deps) | `python3 mcp/server.py` | any harness with MCP, zero pip installs |
| **Python engine** (full pipeline) | `uwae acquire <url> --json` | crawls, sessions, browser escalation, retries |

### 1. Rust binary

```sh
cargo install --git https://github.com/username9999-sys/uwae --root ~/.cargo uwae-fetch
uwae-fetch https://example.com            # markdown on stdout
uwae-fetch https://example.com --json     # {url, final_url, status, title, markdown, bytes}
```

Single ~6 MB binary (dynamically linked against system libc), rustls TLS, 15s timeout, 5 MB cap by default. Built in Rust — same trick as [photocraft](https://github.com/storytold/photocraft) (75k stars) and [anydoc](https://github.com/firecrawl/anydoc) (23k stars).

### 2. MCP server (zero Python dependencies)

`mcp/server.py` is stdlib-only (`urllib` + `html.parser`). One tool: `fetch_url(url, max_bytes?)`.

Claude Code / Codex MCP config:

```json
{
  "mcpServers": {
    "uwae": {
      "command": "python3",
      "args": ["/path/to/uwae/mcp/server.py"]
    }
  }
}
```

### 3. Python engine (the full UWAE)

The artifact-first engine underneath: durable jobs, retry budget, failure isolation (one hanging URL never sinks the batch), browser escalation, session recovery.

```sh
pip install -e .
uwae acquire https://example.com --json
uwae crawl https://example.com --max-urls 50 --concurrency 4
```

## Why this exists (measured, not marketed)

The Python engine was benchmarked head-to-head against [Botasaurus](https://github.com/DedInc/botasaurus) on identical targets, device conditions, and run counts:

| Corpus verdict (E17, 41 comparison instances — read from `docs/benchmark/engine-results-e17.json`) | |
|---|---|
| UWAE wins | **13** |
| Ties | **28** |
| Botasaurus wins | **0** |

Sharpest measured gaps: cause diagnosis **210/210 correct vs 0/210** (precision = recall = 1.0 vs 0.0); DNS failure reaches a terminal classified outcome vs 4–5 unbounded retry cycles. Full evidence in [`docs/benchmark/`](docs/benchmark/) (E14–E22, ADR-019…ADR-027).

Honest caveats, also measured: Python peak allocation per run is 3.04–12.67 MB vs 0.83–4.07 MB, and POST median latency 193–250 ms vs 31–63 ms. That is exactly why the Rust binary is the fast path for single fetches.

## Repo layout

```
uwae/
├── fetcher/          # Rust binary: uwae-fetch <url> → markdown
├── mcp/server.py     # stdlib-only MCP server, tool: fetch_url
├── skills/uwae/      # Agent Skill (npx skills add ... --skill uwae)
├── src/              # Python engine (pip install -e .)
├── tests/            # pytest suite
└── docs/benchmark/   # E14–E22 differential evidence vs Botasaurus
```

## License

MIT — see [LICENSE](LICENSE).
