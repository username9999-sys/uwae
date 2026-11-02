# ADR-012: Access Classifier

## Status
Accepted (2026-10-21, roadmap step 4 of the updated implementation order)

## Context

The access control plane requires a deterministic classifier that turns raw
observations into a bounded access state per attempt (INSTRUCTION.md Spec v2
§3–§4.1, Milestone B). The Fase 2 contracts (`access/model.py`) already fixed
the observation/hypothesis separation and the consistency rules; the classifier
is the first consumer that produces decisions from evidence.

Key spec constraints:

- "mulailah dari aturan deterministik yang hasilnya dapat diverifikasi" — no
  ML before a labeled failure corpus exists (§3).
- "Jangan membuat aturan seperti `403 → challenge → browser` secara universal"
  (§3.1) — a bare 403 is ambiguous (permission, application rule,
  authentication, server policy).
- Every decision must be traceable to evidence with a bounded reason code
  (§3.2–§3.3, ACP §2.2).
- UNKNOWN must remain a legal outcome when evidence is insufficient (§5
  diagnosis quality: proportion of UNKNOWN is a measured metric).

## Decision

1. **Nine-value `AccessState` enum** (`access/model.py`, Spec v2 §4.1):
   `ACCESS_GRANTED, AUTH_REQUIRED, RATE_LIMITED, CHALLENGE_PRESENT,
   JAVASCRIPT_REQUIRED, CONTENT_INVALID, NETWORK_FAILURE, ACCESS_DENIED,
   UNKNOWN`. It is the per-attempt output; `OriginState`/`SessionState`
   remain the cross-attempt machines and are updated by the planner, not the
   classifier.

2. **Exact evaluation order of §3.1** implemented in `access/classifier.py`:
   network error → explicit rate limit (429 or Retry-After header) → explicit
   auth (401 or login form) → explicit denial (403 **without** challenge
   marker) → challenge evidence → target content valid → JavaScript evidence →
   response received → UNKNOWN. Earlier rules win; the 403-with-challenge case
   therefore resolves to `CHALLENGE_PRESENT`, and 200 + login form + valid
   target resolves to `AUTH_REQUIRED`.

3. **Bounded signal vocabulary** (`classifier.Signal`): `http.status`,
   `http.header.retry-after`, `body.marker.login-form`,
   `body.marker.challenge`, `body.marker.target`, `js.required`,
   `network.error`. Unknown signals are ignored by the rules — an
   unrecognized observation can never produce a success state; with no known
   signal the result is UNKNOWN.

4. **Retry-After parsing is deterministic** (`parse_retry_after`): accepts
   delta-seconds and HTTP-date, clamps past dates to 0.0, returns `None` for
   unparseable values. `now` is supplied by the caller — the classifier
   contains no clock and no id generation, so identical inputs produce
   identical assessments (Milestone B pass criterion).

5. **Confidence is a fixed categorical constant per rule** (HIGH 0.95 /
   MEDIUM 0.75 / LOW 0.35), per §3.2: "gunakan kategori keyakinan dan reason
   code terlebih dahulu". Calibration against a labeled corpus is deferred
   until the benchmark harness produces one; no finer-grained probabilities
   are fabricated before then.

6. **Reason-code mapping stays within the bounded enum**: two additions were
   required — `LOGIN_FORM_PRESENT` (a login page returns 200; `HTTP_4XX` would
   be wrong) and `UNKNOWN` (the UNKNOWN state still needs a terminal reason
   code). Everything else maps to existing codes (`DNS_FAILURE`, `TLS_ERROR`,
   `TIMEOUT`, `CONNECTION_ERROR`, `HTTP_429`, `HTTP_4XX`, `HTTP_5XX`,
   `CHALLENGE_DETECTED`, `CONTENT_INVALID`, `OK`).

7. **`AccessAssessment` extended backward-compatibly** with defaulted fields
   `state`, `recommended_action`, `retry_after_seconds` (Spec v2 §4.1
   contract). The existing `hypothesis` field is kept and mapped from state
   (`CONTENT_INVALID → CONTENT_MISMATCH`, etc.); all 27 Fase 2 contract tests
   pass unchanged.

8. **Confusion-matrix helpers** (`confusion_matrix`, `precision_recall`) live
   in the classifier module as pure functions for the labeled-fixture harness
   (Milestone B deliverable); zero denominators return 0.0.

## Alternatives Considered

- **Machine-learned classifier first** — rejected: no labeled corpus exists
  yet; Spec v2 mandates deterministic rules first (§3).
- **Per-site regex heuristics in the classifier** — rejected: site-specific
  logic belongs in target rules/validation config, not in the shared
  classifier; it would break the reproducibility gate.
- **Treating any 403 as challenge/bot detection** — rejected explicitly by
  §3.1; reproduced as a false-positive test (`test_plain_403_not_challenge`).
- **Classifier mutating OriginState directly** — rejected: mixing per-attempt
  diagnosis with cross-attempt origin state violates ACP §2.1 independence;
  the planner (step 5) owns origin transitions.
- **5xx → NETWORK_FAILURE** — rejected: a 5xx response was received; it is
  `CONTENT_INVALID` with hypothesis `APPLICATION_ERROR` and reason `HTTP_5XX`.
  Network failure is reserved for transport-level errors (DNS/TLS/timeout/
  connection).
- **503 + Retry-After → CONTENT_INVALID** — rejected: Retry-After is an
  explicit rate-limit signal per §3.1 rule 2; the header wins over the status
  class. Recorded as a precedence test.

## Consequences

- The strategy planner (step 5) consumes `state` + `recommended_action` +
  `retry_after_seconds` and owns origin/session/job transitions; it must never
  re-derive classification from raw observations.
- Transport adapters must emit observations using the bounded signal
  vocabulary; new signals require a classifier version bump
  (`classifier-1.0.0` → next) so lineage stays auditable.
- Labeled fixtures for the nine classes are now executable as unit tests
  (`tests/test_classifier.py`, 42 tests); the benchmark harness (step 8) can
  reuse `confusion_matrix`/`precision_recall` for the G3 gate (precision/recall
  per class reported).
- Confidence constants are placeholders until calibrated; any tuning must go
  through the labeled corpus, not ad-hoc edits.
- UNKNOWN proportion is measurable from assessments and must be reported in
  benchmark summaries rather than hidden.

## Evidence

- `src/universal_web_acquisition/access/classifier.py` (deterministic §3.1 order)
- `src/universal_web_acquisition/access/model.py` (AccessState, ReasonCode additions, extended AccessAssessment)
- `tests/test_classifier.py` (42 tests: per-class, precedence, FP/FN, Retry-After, determinism, lineage, confusion matrix)
- `python run_tests.py` → 71 passed (27 pre-existing contract tests unchanged)
- INSTRUCTION.md Spec v2 §3–§4.1, Access Control Plane §2, Milestone B criteria
