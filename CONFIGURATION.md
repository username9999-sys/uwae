# Configuration

## Honest summary

The engine does **not** read a configuration file. Behavior is controlled by:

1. **CLI flags** — see the README for the full surface (`acquire`, `crawl`, `discover`, `calibrate`, `list`, `show`, `reprocess`)
2. **Constructor arguments** — `AcquisitionEngine(db_path=...)` / `JobRepository(db_path=...)` set the SQLite database path (default: `jobs.db` in the current directory)

There is no YAML/JSON config file, no `/etc/` path, and no environment-variable layer. (An earlier `Config` class and a default `config.json` existed as Phase-0 scaffolding but were never wired into the engine — removed after a dead-code audit; see git history if you need them.)

## Database path

- CLI: `--db <path>` on `acquire` / `crawl` / `list` / `show` / `reprocess`
- Programmatic: `AcquisitionEngine(db_path="path/to/jobs.db")`

## Artifact storage

- CLI: `--artifacts-dir <path>` (default: `artifacts`)
