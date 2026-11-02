# ADR-014: CDP Browser Adapter

## Status
Accepted (2026-10-21, pasca-roadmap: browser path wiring). Supersedes the
"no browser adapter is built now" clause of ADR-011 decision 4 — the spike
evidence that decision deferred on now exists.

## Context

- ADR-011 decision 4 sanctioned raw CDP as the minimal browser path and
  deferred a full browser adapter until the browser capability spike phase.
- The spike (roadmap step 7, `tests/test_browser_cdp.py`) produced the
  evidence: cold start ~5.0 s, first render ~2.1 s / warm ~0.4 s, chromium
  RSS ~166–167 MB, JS execution verified on the /js fixture, UA override
  mandatory (ADR-011 decision 7).
- The worker↔ACP integration (see roadmap "Pasca-roadmap integration") made
  the planner's `USE_BROWSER` decision reachable — but it had no executor:
  `browser_available` was hardcoded `False`, so the escalation chain stopped
  at transport switching.

## Decision

1. **`browser/adapter.py` — `CDPBrowserAdapter`**, same contract as the HTTP
   adapters (`name`/`can_handle`/`acquire`), backed by raw CDP
   (`browser/cdp.py`), zero new dependencies. The worker executes it through
   the identical path — no browser-specific branch in the decision logic.

2. **One chromium lifecycle per `acquire`** (start → render → stop). The
   ~5 s cold start is measured and documented, not hidden; lifecycle reuse
   across attempts is deferred until the benchmark harness shows the cost
   matters (measure → optimize → measure, not the reverse).

3. **Failure mapping into the bounded reason codes**: runtime unavailable
   (binary missing, CDP endpoint never appears) → `CAPABILITY_MISSING`;
   per-page navigation/DOM/CDP failures → `CONNECTION_ERROR` (retryable —
   the planner bounds it like any network failure).

4. **`status_code` 0 from the performance API maps to 200**: DOM
   `complete` + extracted content is the evidence of successful navigation;
   a missing `responseStatus` navigation entry is not a failure.

5. **Worker wiring**: `JobWorker(browser_adapter=...)` — the planner's
   `browser_available` becomes `self.browser_adapter is not None`;
   `USE_BROWSER` switches the current adapter to `"browser"`; returning to
   HTTP transports stays possible through the normal bounded escalation.

6. **Bounded content-marker detection** in the worker's observation builder
   makes `JAVASCRIPT_REQUIRED`/`CHALLENGE_PRESENT` reachable from real 2xx
   responses: conservative marker lists (JS gates: "please enable
   javascript", "enable javascript to"; challenge interstitials:
   "cf-challenge", "just a moment", "challenge-platform", "checking your
   browser"). A gated/interstitial page reports target marker `missing` —
   the gate is not the target content.

7. **The /js fixture became a true JS gate**: the gate text is placed inside
   the `<h1>` and *replaced by the page script* at render time — an HTTP
   fetch carries the marker, a browser render does not. This gives the
   differential benchmark an honest JS-gate scenario instead of a synthetic
   placeholder.

## Alternatives Considered

- **Playwright-based adapter** (the Phase 2 roadmap item) — rejected for
  now: forces the two-environment split (glibc-only wheel); raw CDP is
  proven single-environment on this device.
- **Persistent chromium lifecycle in the worker** — deferred: reusing one
  chromium across attempts saves ~5 s per attempt but adds lifecycle/crash
  management; measure first via the benchmark, then optimize.
- **Header-based challenge detection** (`cf-mitigated` header) — deferred:
  `TransportFailure` does not carry response headers in v1; body-marker
  detection chosen; header signals arrive when failure objects carry them.
- **Broad marker lists** (e.g., bare "captcha") — rejected: false-positive
  prone; the bounded lists keep FP risk low, and the actual FP rate will be
  measured in Milestone B (confusion matrix), not assumed.

## Consequences

- The adaptive escalation chain is complete and executable end-to-end:
  HTTP → transport switch → browser → user intervention.
- Challenge/JS-gate detection relies on body markers until a richer
  validator exists; the marker lists are part of the worker's versioned
  surface and their precision/recall is a Milestone B deliverable.
- Browser attempts cost ~5 s cold start each; the planner's budget gates
  bound the total number of attempts (including browser cycles).
- `USE_BROWSER` without a wired `browser_adapter` remains impossible
  (planner gate), preserving the HTTP-only usable mode (INSTRUCTION.md
  Mandatory Phase 5).

## Evidence

- `src/universal_web_acquisition/browser/adapter.py`, `browser/cdp.py`
- `tests/test_worker_acp.py`: `TestBrowserEscalation` (2 fake-adapter tests:
  JS-gate escalation succeeds; persistent challenge → NEEDS_USER after
  bounded browser cycles), `TestBrowserRealCDP` (end-to-end chromium proof:
  HTTP fetch → JS-gate → render → `rendered-by-js` in artifact → SUCCEEDED)
- `tests/test_browser_cdp.py` (spike evidence: cold start, render, RSS, UA)
- `python run_tests.py` → 144 passed (101 s, includes the real-chromium test)
- INSTRUCTION.md Spec v2 §4.2 (decision table), ADR-011 (browser path),
  ADR-013 (planner USE_BROWSER contract)
