# ADR-015: Per-Origin Target Rules (soft-404 → content_invalid)

## Status
Accepted (2026-10-24, post-roadmap §3.1 completion — evidence: ampnavi soft-404 runs)

## Context

The second real-target benchmark (ampnavi188.com, commit `da7621d`) proved a
**universal soft-404**: robots.txt, homepage, sitemap.xml, and a non-existent
probe path all returned the identical 215,804-byte artifact — the server
answers every path with `200` + technically valid HTML.

The cross-path soft-404 detection (commit `e99dae6`) records the evidence
(`soft404_suspected` event: url + first_seen_url + sha256) but keeps the
diagnosis honest: the content **is** valid, so the classifier state stays
`ACCESS_GRANTED` and the planner ACCEPTs. That is correct by §3.1 — identical
content across paths is not *universally* invalid (single-page apps and
templated sites legitimately serve the same HTML shell on every route), and
Spec v2 §3.1 explicitly forbids universal rules ("jangan membuat aturan
universal").

The gap: an operator who **knows** that for one specific origin such content
is not the target content had no way to say so. The engine would keep
ACCEPTing soft-404 pages for that origin forever, and downstream consumers
would store junk as if it were acquired target content.

## Decision

1. **`access/target_rules.py` — `TargetRules`, explicit per-origin
   registration only.** `register_soft404_invalid(origin)` /
   `soft404_as_invalid(origin)`. No defaults, no discovery, no inference:
   a rule exists only for an origin the operator explicitly registered in
   this run.

2. **The rule changes the DECISION, never the EVIDENCE.** Inside the worker's
   ACCEPT branch, *after* the `soft404_suspected` event is recorded, a
   registered rule cancels the acceptance: `job.mark_failed("content_invalid:
   soft-404 terkonfirmasi — … (aturan per-situs)")`. The audit event, the
   attempts, and the error text naming the rule all stay on the record.

3. **Without a registered rule, behavior stays technically honest** — valid
   content is `ACCESS_GRANTED`, exactly as before. This is the §3.1
   invariant: the engine never decides on its own that duplicate content is
   invalid.

4. **Trigger is confirmed cross-path duplication only**: same origin, same
   SHA-256, `first_seen_url != job.url`. The *first* acquisition of a path is
   never failed by the rule — there is no cross-path evidence yet.

5. **CLI wiring is explicit per invocation**: `acquire --strict-soft404`
   registers the target URL's origin; `crawl --strict-soft404` registers the
   crawl origin. Rules are never persisted or guessed from history.

6. **Policy lives above diagnosis, not inside it.** The classifier is not
   touched: content validity is an evidence question; "this origin's
   duplicates are junk" is an operator policy. The worker decision layer is
   where policy belongs.

## Alternatives Considered

- **Universal soft-404 rule** (any cross-path duplicate = invalid) —
  rejected: §3.1 forbids it; SPA/templated sites make it a false positive
  generator.
- **Auto-registration after N suspected events** — rejected: self-fulfilling.
  Repetition is not ground truth; the operator's declaration is.
- **Teach the classifier a "soft404" state** — rejected: the classifier
  consumes bounded run-time signals, and "operator says so" is not a signal
  the transport produces. It would also break the §3.1 deterministic
  evaluation order for every other origin.
- **Persist rules in a config file / database** — deferred: current
  consumers (CLI flags, benchmark harness) pass rules in-process;
  persistence becomes relevant only with a long-running daemon, and can be
  added to `TargetRules` without changing the worker contract.

## Consequences

- Accepting a soft-404 page is now a **per-origin, auditable policy
  decision**: the job record carries both the `soft404_suspected` evidence
  and the FAILED `content_invalid` error naming the rule — no silent
  behavior.
- Calibration is unaffected: the rule acts *after* classification, so
  assessment events (and the §3.2 corpus built from them) keep the honest
  observed state.
- Tests: 3 in `tests/test_worker_acp.py::TestTargetRules` — registered
  origin → FAILED `content_invalid` with evidence intact; no rules → both
  paths SUCCEED with evidence still recorded; a rule for another origin does
  not apply.
- Future per-origin policies (e.g., origin-specific rate-limit budgets)
  should extend `TargetRules` rather than adding ad-hoc worker branches.
