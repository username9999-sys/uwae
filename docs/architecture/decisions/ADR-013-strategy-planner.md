# ADR-013: Strategy Planner

## Status
Accepted (2026-10-21, roadmap step 5 of the updated implementation order)

## Context

The access classifier (ADR-012) produces a per-attempt `AccessAssessment` with
`state`, `recommended_action`, and `retry_after_seconds`. The strategy planner
must turn that assessment into one explainable next action (INSTRUCTION.md
Spec v2 §4) under hard constraints:

- "Planner versi pertama harus berupa aturan deterministik yang dapat diuji"
  (§4) — no ML, no scoring before a labeled failure corpus exists.
- §4.2 decision table fixes the expected decision per evidence class
  (persist valid content; honour Retry-After; recover sessions via authorized
  auth; check browser capability for JS/challenge; stop on explicit denial;
  never rotate transports forever).
- ACP §2.2: `DENIED` must never be auto-resolved by replaying the request
  through every transport; `NEEDS_USER` must never auto-resolve to success.
- ADR-011 decision 3: retry is bounded (`RetryPolicy`, max 0..10, `None`
  delay = budget exhausted); the E6 anti-pattern (unbounded `while True`)
  must be impossible by construction.

## Decision

1. **Bounded `NextAction` enum** (`access/planner.py`): `ACCEPT`,
   `RETRY_SAME_TRANSPORT`, `SWITCH_TRANSPORT`, `USE_BROWSER`,
   `WAIT_RETRY_AFTER`, `RECOVER_SESSION`, `NEEDS_USER`, `INSPECT_CONTENT`,
   `COLLECT_MORE_EVIDENCE`, `ABORT`. Every decision carries a `ReasonCode`,
   a human-readable `rationale`, `planner_version`, and caller-supplied
   `decision_id`/`decided_at` — pure function, reproducible bit-for-bit.

2. **Decision table per assessment state** (§4.2, one rule each):
   `ACCESS_GRANTED → ACCEPT`; `RATE_LIMITED → WAIT_RETRY_AFTER` (server's
   seconds) or `RETRY_SAME_TRANSPORT` with policy backoff; `AUTH_REQUIRED →
   RECOVER_SESSION`; `CHALLENGE_PRESENT → USE_BROWSER` if a runtime exists,
   else `NEEDS_USER`; `JAVASCRIPT_REQUIRED → USE_BROWSER` else `ABORT` with
   `CAPABILITY_MISSING`; `ACCESS_DENIED → NEEDS_USER` (never retried);
   `NETWORK_FAILURE → RETRY_SAME_TRANSPORT` (if retryable + budget) →
   `SWITCH_TRANSPORT` → `ABORT`; `CONTENT_INVALID → INSPECT_CONTENT`;
   `UNKNOWN → COLLECT_MORE_EVIDENCE`.

3. **Budget gate precedes Retry-After.** A server-supplied wait never
   overrides the exhausted retry budget: when `retry_attempt >
   max_retries`, the decision is `ABORT`/`BUDGET_EXHAUSTED` even if
   `Retry-After` is present. Waiting longer is not a licence for more
   attempts.

4. **Content problems are not transport problems.** `CONTENT_INVALID` and
   `UNKNOWN` never trigger transport rotation — the §4.2 table sends them to
   inspection / evidence collection, bounded by the same attempt budget
   (each cycle consumes one attempt; when the budget is out the decision is
   terminal with the observed reason). This deliberately narrows the
   escalation path compared to a naive "try another client" fallback, which
   the spec names as an anti-pattern.

5. **Escalation order is cost-ordered and bounded**: same transport (policy
   backoff) → caller-supplied `untried_transports` list (each switch consumes
   one entry; the caller shrinks it) → browser path (only when a runtime is
   available and the state demands it) → user intervention. The planner
   never invents transports and never loops: every branch either terminates
   or strictly consumes budget/alternatives.

6. **`ACCESS_DENIED → NEEDS_USER`, not `FAILED`.** An explicit denial is a
   policy condition a human may resolve (authorized access path); marking it
   `FAILED` would hide the actionable state. The job layer's
   `assert_needs_user_not_auto_resolved` guarantees it cannot silently
   become success.

7. **Non-retryable network reasons skip the retry branch** and go straight
   to transport escalation (or abort when none remain) — `RetryPolicy.
   is_retryable` is the single source of truth for the retryable set.

## Alternatives Considered

- **Weighted scoring** `score(s) = w_p·P_s − w_t·T_s − w_m·M_s − w_f·F_s`
  (§4.1) — deferred: requires calibrated success/latency/memory data from the
  benchmark harness (step 8). Deterministic rules first, per §4.
- **Rotate transports on every error** (baseline-style fallback chains) —
  rejected: Spec v2 §4.2 explicitly warns all fallbacks can fail from the
  same cause; rotation is bounded and evidence-driven only.
- **`CONTENT_INVALID → SWITCH_TRANSPORT`** (an earlier draft of rule 7) —
  rejected after re-reading the §4.2 table: a wrong/empty page is not fixed
  by another HTTP client. Replaced with `INSPECT_CONTENT` + budget-bounded
  re-classification (the classifier promotes it to `JAVASCRIPT_REQUIRED`
  when JS evidence appears).
- **Planner mutating job/origin state directly** — rejected: the planner
  proposes; the worker applies transitions through the consistency rules
  (`assert_terminal_reason`, `assert_retry_wait_has_trigger`), keeping the
  planner pure and testable.

## Consequences

- The worker loop (step 8 integration) must increment `retry_attempt` on
  every new attempt — including non-retry actions such as
  `INSPECT_CONTENT`/`RECOVER_SESSION` — because the planner uses it as the
  total-attempt budget. This is documented in the module docstring.
- Decision quality becomes measurable on labeled fixtures: each decision's
  `(state → action)` pair can be compared against the §4.2 ground truth in
  the differential benchmark (G4 gate: no unbounded retry, no illegal
  transition).
- `WAIT_RETRY_AFTER` decisions carry the server's own seconds in
  `wait_seconds`; the job layer converts this into a `RETRY_WAIT` trigger
  satisfying `assert_retry_wait_has_trigger` by construction.
- New actions require a planner version bump (`planner-1.0.0` → next) so
  decision lineage stays auditable.

## Evidence

- `src/universal_web_acquisition/access/planner.py` (decision table, budget semantics)
- `tests/test_planner.py` (22 tests: per-state decisions, budget gate before Retry-After, bounded escalation, DENIED never retried, determinism, auditability)
- `python run_tests.py` → 131 passed (43 s) including 20 adapter tests, 13 session-manager tests, 5 browser-spike tests
- INSTRUCTION.md Spec v2 §4 (decision table, anti-cycle), Access Control Plane §2.2, ADR-011 (bounded retry), ADR-012 (classifier contract)
