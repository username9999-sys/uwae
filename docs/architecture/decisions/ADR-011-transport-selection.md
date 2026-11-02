# ADR-011: Transport Selection

## Status
Proposed (2026-10-20, based on completed G0 milestone evidence)

## Context

The engine requires a transport layer selected on evidence, not popularity or README
feature counts (INSTRUCTION.md, Fase 1: "Pilih adapter berdasarkan hasil dan
kapabilitas"). The G0 milestone produced the following verified evidence:

### Environment constraints
- Dual Python runtimes: **Termux Python 3.14.6 (bionic)** — runs the project — and
  **PRoot Python 3.14.4 (glibc)**. Wheels are not interchangeable between them
  (Playwright installs only under glibc; curl_cffi ships an `android_24_arm64_v8a` wheel
  for bionic). See `docs/audit/environment-report.md`.
- No root, no PC. Android runtime (`am`, `pm`) is reachable from PRoot.

### Transport capability matrix (verified, Termux Python)
| Transport | Version | TLS fingerprint | HTTP/2 | HTTP/3 | brotli | Benchmark (E5) |
|---|---|---|---|---|---|---|
| curl_cffi | 0.16.3 | ✅ (`impersonate`) | ✅ | ❌ | ✅ native | wins redirect + brotli; competitive everywhere |
| httpx | 0.28.1 | ❌ | ✅ (h2 installed) | ❌ | ✅ (via brotli) | slowest in 5/6 scenarios |
| requests | 2.33.0 | ❌ | ❌ | ❌ | ✅ (via brotli) | mid-pack |
| urllib3 | 2.7.0 | ❌ | ❌ | ❌ | ✅ | smoke OK (not benchmarked separately) |
| aiohttp | 3.14.1 | ❌ | ✅ | ❌ | ✅ | smoke OK (async; not benchmarked) |
| niquests | 3.21.2 | ❌ | ✅ | ⚠️ h3 pending server `alt-svc` | ✅ | smoke OK (E7) |

### Differential benchmark (E5, `docs/benchmark/transport-results.json`)
6 deterministic scenarios × 4 engines, **24/24 byte-for-byte correct**. Baseline
(botasaurus-venv requests 2.34.2) wins 4/6; curl_cffi wins 2/6 (redirect chain,
brotli) and is consistently within tens of ms of the baseline. This is a baseline
measurement, not a superiority claim.

### Browser paths (E2/E3)
- **Raw CDP via `websockets` works from Termux Python** driving the PRoot chromium
  binary (Chromium 151, headless verified) — zero new dependencies.
- **Playwright 1.63.0 works only under PRoot Python** (glibc); launches the already-
  downloaded `~/.cache/ms-playwright` chromium with zero downloads.
- Chromium's default UA reports `Linux x86_64` on an aarch64 device — UA override is
  mandatory for any browser use.

### Baseline defect evidence (E6)
`botasaurus_requests.retry_on_network_error` (pinned 4.0.97 / botasaurus_requests
4.0.38) implements an **unbounded `while True` retry** for errors matching
`dial tcp: lookup … no such host` — reproduced at runtime (3 attempts observed in a
50 s window, process killed by timeout). Non-DNS errors are re-raised immediately.

## Decision

1. **Primary HTTP transport: `curl_cffi`.** Rationale: only verified TLS-fingerprint
   layer on this platform, native brotli, best redirect-chain latency, competitive in
   all scenarios. Fingerprinting is a capability the access control plane needs for
   modern targets; it cannot be retrofitted onto requests/httpx.

2. **Secondary transports behind a `TransportAdapter` registry: `httpx` (async,
   HTTP/2) and `requests` (ecosystem fallback).** Selection between them is made by
   the access assessment per request (evidence-based), never hardcoded. `niquests`
   and `aiohttp` remain registry options; niquests is promoted only after HTTP/3 is
   verified against an h3-advertising server.

3. **Retry policy: bounded, with reason codes.** Max retries (default 3) with
   exponential backoff; every terminal transition records a reason code. Unbounded
   retry loops are prohibited — the baseline's unbounded `while True` (E6) is the
   documented anti-pattern this rule exists to prevent.

4. **Browser path: raw CDP over `websockets` from Termux Python** (E3) is the
   sanctioned minimal browser path — it keeps the engine single-environment. The
   Playwright/PRoot path (E2) is recorded as an optional full-feature alternative,
   deferred until the browser capability spike phase (per Rencana v1 §7 ordering:
   browser spike comes after session recovery). No browser adapter is built now.

5. **Content-encoding: gzip and brotli support is mandatory** for every transport
   adapter (E4 verified both; baseline venv parity established).

6. **Single-environment strategy for HTTP:** all HTTP transports run under Termux
   Python. The CDP path controls the glibc chromium binary as a subprocess — proven
   to work cross-environment (E3) — avoiding a split runtime for the core engine.

7. **UA override is mandatory** in every transport and browser adapter (E2 finding).

## Alternatives Considered

- **`requests` as primary** — richest ecosystem, but no TLS fingerprint and slower
  than curl_cffi in 5/6 benchmark scenarios. Rejected as primary; kept as fallback.
- **`httpx` as primary** — async + HTTP/2, but slowest in the benchmark (redirect
  chain 114.9 ms vs curl_cffi 47.6 ms). Kept for async workloads only.
- **`niquests` as primary** — HTTP/3-ready, but h3 negotiation unverified on this
  platform; revisit after an h3-advertising fixture exists.
- **Playwright as the primary browser path** — full-featured, but forces a
  two-environment split (glibc-only wheel). Deferred to the browser spike phase.
- **Unbounded retry (baseline-style)** — rejected with reproduced evidence (E6).

## Consequences

- The `TransportAdapter` registry (ADR-003 contract) gains capability metadata:
  `tls_fingerprint`, `http2`, `http3`, `brotli`, `async` — the access assessment
  selects adapters from this metadata plus per-origin evidence.
- The E5 benchmark harness becomes the regression gate: any transport change must
  re-run `transport_bench` and keep 24/24 correctness.
- curl_cffi dependency risk: Android arm64 wheels track upstream releases; a
  broken wheel release would require falling back to httpx/requests until fixed.
- Raw CDP requires implementing page lifecycle handling (target discovery, session
  routing) that Playwright provides for free — accepted cost for
  single-environment operation; revisit at the browser spike phase.
- HTTP/3 support remains open until verified against an h3-advertising fixture.

## Evidence

- `docs/audit/g0-audit-report.md` §7 (E1–E7 experiment log)
- `docs/benchmark/transport-results.json` (E5 raw results, 24/24 correct)
- `docs/audit/environment-report.md` (dual-Python facts, transport matrix)
- `tests/regression/e6_botasaurus_dns_retry.py` (baseline infinite-retry reproduction)
- INSTRUCTION.md (mandate, L.3 deliverable, access control plane contracts)
