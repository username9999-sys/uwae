# ADR-007: Adaptive Access Assessment and Recovery

## Status
Proposed

## Context
Modern web resources employ sophisticated anti-bot measures, rate limiting, and access controls that require intelligent response strategies. Based on the competitive analysis, while Botasaurus has some challenge detection capabilities (anti-detect-driver.md), it lacks a systematic approach to access assessment, strategy planning, and recovery that adapts to changing conditions.

## Decision
We will implement an adaptive access engine with the following characteristics:

### Access Assessment System
1. **Multi-Signal Evidence Collection**: Collection of diverse signals for access assessment:
   - HTTP signals: Status codes, headers, redirect chains
   - Content signals: HTML structure, text content, JavaScript requirements
   - Behavioral signals: Request timing, response patterns, session characteristics
   - Technical signals: TLS/SSL characteristics, DNS resolution, connection properties
   - Contextual signals: Geographic indicators, server characteristics, technology stacks

2. **Evidence Model**: Each piece of evidence includes:
   - Source: Where evidence came from (http_header, html_content, js_behavior, etc.)
   - Type: What kind of evidence (status_code, content_pattern, timing_anomaly, etc.)
   - Value: The observed value
   - Confidence: Reliability of this evidence (0.0-1.0)
   - Timestamp: When evidence was collected
   - Details: Additional context information

3. **Access State Classification**: Based on evidence, resources are classified into states:
   - ACCESS_GRANTED: Resource successfully acquired with expected content
   - AUTH_REQUIRED: Authentication is required to access resource
   - RATE_LIMITED: Resource is temporarily unavailable due to rate limiting
   - CHALLENGE_PRESENT: Anti-bot challenge (CAPTCHA, etc.) is present
   - JAVASCRIPT_REQUIRED: Resource requires JavaScript execution for expected content
   - CONTENT_INVALID: Resource accessible but content doesn't match expectations
   - NETWORK_FAILURE: Network-level failure prevented acquisition
   - ACCESS_DENIED: Explicitly denied access (403 with denial messaging)
   - UNKNOWN: Insufficient evidence to determine state

4. **Confidence Scoring**: Each classification includes a confidence score (0.0-1.0) indicating reliability.

### Adaptive Strategy Planner
1. **Evidence-Based Decision Making**: Strategy selection based on:
   - Current access assessment (state and confidence)
   - Historical success rates for strategies on similar resources
   - Available capabilities (what adapters/plugins are accessible)
   - Resource costs (time, memory, CPU, battery)
   - Resource constraints (current system load, network conditions, etc.)
   - Policy constraints (user-defined rules, rate limits, etc.)
   - Previous attempts on this resource (to avoid infinite loops)

2. **Strategy Options**: The planner can choose from:
   - HTTP Request (standard GET/POST with current adapter)
   - HTTP Request with different parameters (headers, user agent, etc.)
   - Browser Automation (standard Selenium/Playwright)
   - Browser with specific configurations (different user agent, proxy, etc.)
   - Delayed Retry (wait before retrying with same approach)
   - Session Recovery (attempt to recover and reuse existing session)
   - Authentication Flow (initiate login/authentication process)
   - Challenge Solving (attempt to solve CAPTCHA or other challenge)
   - Human Intervention Request (request user assistance)
   - Policy-Based Action (follow user-defined rules: wait, escalate, abandon, etc.)
   - Abandon: Stop trying to access this resource

3. **Decision Factors**: The planner weighs:
   - Probability of success for each strategy
   - Resource cost (time, memory, etc.) of each strategy
   - Risk of negative outcomes (getting blocked, increasing rate limits, etc.)
   - Historical effectiveness of strategies
   - Compliance with access policies (rate limits, authentication requirements, etc.)
   - Available retry budget and attempt limits

4. **Learning System**: The planner improves over time by:
   - Recording outcomes of strategy decisions
   - Updating success probability estimates
   - Adjusting confidence weights for different evidence types
   - Refining strategy cost estimates
   - Adapting to changing resource characteristics

### Recovery Mechanisms
1. **Session Recovery**:
   - Session state persistence (cookies, tokens, authentication state)
   - Session expiration detection and recovery
   - Credential re-use where secure and appropriate
   - Re-authentication flows for expired sessions
   - Secure credential storage (encrypted where possible)

2. **Job Recovery**:
   - Checkpointing of long-running operations
   - Idempotent operations where possible to prevent duplicate work
   - Persistent job state enabling recovery after process termination
   - Attempt tracking to prevent infinite retry loops
   - Resource usage tracking to inform recovery decisions

3. **Access Recovery**:
   - Backoff strategies (exponential with jitter) for rate-limited resources
   - Respect of Retry-After headers when present
   - Session-based recovery for authenticated resources
   - Credential refresh mechanisms
   - Fallback to alternative access methods when primary fails

### Policy Engine
Access decisions are governed by configurable policies:
1. **Rate Limit Policies**: How to respond to rate limiting signals
2. **Authentication Policies**: When and how to pursue authentication
3. **Challenge Policies**: How to handle different challenge types
4. **Retry Policies**: When to retry, with what backoff, and attempt limits
5. **Resource Policies**: How to manage system resources during access attempts
6. **Escalation Policies**: When to escalate to more resource-intensive approaches
7. **Abandonment Policies**: When to give up on a resource

## Consequences

### Positive
- Intelligent response to complex access conditions
- Reduced wasted resources on futile attempts
- Improved success rates through adaptive strategies
- Better resource utilization through cost-aware decision making
- Systematic learning and improvement over time
- Clear separation between assessment, planning, and execution
- Extensible policy system for different use cases and risk tolerances

### Negative
- Increased complexity in access decision making
- Need for training data or historical records to enable learning
- Potential for overfitting to historical patterns
- Increased storage requirements for evidence and history
- More difficult to predict behavior in novel situations

## Implementation Plan
1. Define access evidence and assessment models
2. Implement evidence collectors for HTTP, content, and technical signals
3. Build access state classifier with confidence scoring
4. Develop adaptive strategy planner with evidence-based decision making
5. Implement recovery mechanisms for sessions, jobs, and access
6. Create policy engine for governing access decisions
7. Build feedback loop for learning from strategy outcomes
8. Integrate with job scheduler and transport adapters

## Related Decisions
- ADR-001: Core Job Model and Durable State
- ADR-002: Discovery and Scope Policy
- ADR-003: HTTP and Browser Adapter Contracts
- ADR-004: Artifact Pipeline and Integrity Verification
- ADR-005: Integrity Verification and Format Identification
- ADR-006: Capability Registry and Plugin Contracts
- ADR-008: Cache Separation and Invalidation
- ADR-009: Concurrency, Cancellation, and Backpressure
- ADR-010: Observability, Security, and Benchmark Methodology

## Validation
This decision will be validated by:
- Unit tests for evidence collection and assessment models
- Integration tests for access state classification accuracy
- Benchmark scenarios measuring strategy selection effectiveness
- Tests showing improved success rates over static approaches
- Learning system validation (improvement over repeated similar challenges)
- Policy compliance testing (ensuring policies are followed)
- Performance measurements of decision-making overhead

