# Development Setup

## Prerequisites

- Python 3.11+ (developed on Python 3.14, Termux/PRoot aarch64)
- Git

## Setup

The project lives as a subdirectory of a local monorepo. To work on it:

```bash
cd /root/universal-web-acquisition
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `[dev]` extra installs the test and tooling dependencies (pytest, ruff, black, ...).

## Running Tests

Tests live flat in `tests/` and need `src` on the path:

```bash
# Full suite
PYTHONPATH=src python -m pytest tests/

# Single file
PYTHONPATH=src python -m pytest tests/test_worker_acp.py -q
```

The suite includes a real-chromium end-to-end test (CDP browser) — it needs a chromium binary; on Termux it runs via the installed chromium package.

Use the **Termux** interpreter, not the PRoot one. On this device `python`
resolves to Termux (3.14.6), which has `curl_cffi` — the transport the engine
uses — so `PYTHONPATH=src python -m pytest tests/` works as written above.
(`/data/data/com.termux/files/usr/bin/python3` is the same Termux build and is
equally fine.)

The PRoot interpreter at `/usr/bin/python3` (3.14.4) does **not** have
`curl_cffi` installed: the suite still collects, but 61 tests fail with
`ModuleNotFoundError: No module named 'curl_cffi'`. That is an environment
mismatch, not a regression — check `sys.executable` before investigating the
code.

## Linting and Formatting

Ruff and Black are configured in `pyproject.toml`:

```bash
ruff check .
black .
```

## Database

Jobs and evidence live in a local SQLite database (`jobs.db` by default, overridable via `--db`). The schema is created idempotently by `JobRepository._init_db()` — there is no migration tool in use (alembic is a declared dependency, but the engine does not run migrations).

## Benchmarks

Benchmark results are committed as evidence under `docs/benchmark/`:

```bash
# E9 engine differential (fixture-based, includes baseline attempt)
PYTHONPATH=src python -c "from universal_web_acquisition.benchmark.engine_bench import main; main()"

# E10 capability bench (fixture-based)
PYTHONPATH=src python -c "from universal_web_acquisition.benchmark.capability_bench import main; main()"
```

Real-target benchmarks require an explicitly authorized target — never run them against a site without the operator's authorization (see INSTRUCTION.md).

## Project Structure

```
src/universal_web_acquisition/
├── access/            # Classifier, planner, observation, calibration, target rules
├── artifact/          # Artifact storage, integrity, file identification (E2)
├── benchmark/         # Fixture server + E5/E8/E9/E10 runners, real-target runner
├── browser/           # CDP browser adapter (ADR-014)
├── cli/               # uwae CLI (acquire/crawl/discover/calibrate/list/show/reprocess)
├── core/              # Job model, worker (ACP cycle), repository, engine
├── discovery/         # Sitemap discovery + HTML link extractor
├── extract/           # Extraction contract + built-in extractors
├── http_transport/    # Adapters, registry, contracts, resume, cache
├── observability/     # Logging/metrics helpers
├── plugins/           # Plugin registry + external plugin loader (ADR-006)
├── session/           # Session state machine, recovery, SQLite store
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
