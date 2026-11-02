# ADR-016: Bounded Concurrent Execution (E6 — ConcurrentJobRunner)

## Status
Accepted (2026-10-25, post-roadmap Tahap H — evidence: engine-results-e11.json)

## Context

TEXT.md Tahap H mandates concurrency/scale (experiment E6). The engine's
execution model was strictly sequential: one `JobWorker` executes one job at
a time (`asyncio.run(worker._execute_job(job))` per call). Per the
measure-first discipline (§43), the E11 baseline was committed FIRST
(`f98b9cf`): sequential throughput 3.320–4.347 jobs/s, p50 ~194–204 ms
through the full engine against the local fixture — so any concurrency
claim would be a comparison against committed numbers, not an assertion.

Two constraints shape the design:

1. **`JobRepository` opens a fresh SQLite connection per method call** —
   naturally thread-safe, but every concurrent worker multiplies write
   contention on one database file.
2. **Transport adapters are not designed for cross-thread sharing** — the
   CDP adapter holds browser state, the caching adapter holds an LRU; the
   worker contract is one-owner-at-a-time.

## Decision

1. **`core/concurrent_runner.py` — `ConcurrentJobRunner`, bounded
   `ThreadPoolExecutor`.** Default 4 threads, **hard cap 16** (`MAX_THREADS`,
   enforced in the constructor; `n_threads < 1` → `ValueError`). No
   unbounded or auto-scaling pool — there is no honest way to claim safe
   scale beyond what was measured.

2. **Worker + repository + adapter per thread** via `threading.local`,
   created once per thread and reused. Isolation by construction: no
   adapter or worker state is ever shared across threads. `worker_factory`
   lets the caller inject the exact wiring (cache, identifier, extractors,
   target rules) so parallel runs are apple-to-apple with sequential ones.

3. **G6 durability preserved**: ALL jobs are enqueued (`save_job`) BEFORE
   any execution starts — visible in the database even if the process dies
   mid-run.

4. **Failure isolation**: one failed job never stops the others; the final
   status list is honest per job (including failures).

5. **Measured, not claimed**: committed evidence (engine-results-e11.json,
   4 scenarios) — concurrent t2 = 5.214 jobs/s (~1.57× vs baseline), t4 =
   5.437 jobs/s (~1.25×). **The speedup is sub-linear and reported as
   such**: per-job `asyncio.run` overhead, SQLite write contention, and the
   localhost fixture are the visible ceilings. No linear-scaling claim is
   made anywhere.

6. **Policy stays at the caller**: `crawl --concurrency N` (commit
   `57b0c34`) — N=1 keeps the sequential path byte-for-byte; N>1 executes
   each BFS level in parallel, with the `--max-urls` quota still binding
   across levels and follow-links provenance (`discovered_via`) still
   recorded by the shared harvest closure.

## Alternatives Considered

- **Asyncio-native concurrency** (single event loop, shared adapters) —
  rejected: adapters are not thread-safe by contract and the worker's
  `asyncio.run`-per-job contract would need a full rewrite for a gain the
  measurements suggest is capped by SQLite + fixture, not by the executor.
- **Shared worker with locks** — rejected: adapter state (CDP keep-alive,
  cache LRU) is not designed for cross-thread sharing; per-thread isolation
  is simpler and honest.
- **Process-based parallelism** — deferred: write contention is already
  visible at 4 threads; processes would multiply DB contention without
  addressing the actual bottleneck.
- **Unbounded/auto-scaling pool** — rejected: cannot claim safe scale
  beyond measured numbers (§43 discipline).

## Consequences

- Parallel runs keep the full evidence lineage — `worker_factory` carries
  the same wiring as sequential (extractors, target rules, identifier,
  cache), so `cache.hit`, `identification`, and `extraction` events appear
  identically in either path.
- The sub-linear ceiling is the honest current state; any future
  optimization (e.g., connection pooling, a persistent event loop) must
  re-run the E11 harness and compare against the committed baseline.
- Tests: 5 runner tests (all succeed, failure isolation, thread bounds,
  empty input, G6 enqueue) + 2 CLI tests (`TestCrawlConcurrency`).
- Future per-origin rate-limit budgets should coordinate through
  `TargetRules` (ADR-015), not ad-hoc thread logic.
