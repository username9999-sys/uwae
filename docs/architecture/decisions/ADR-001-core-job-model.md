# ADR-001: Core Job Model and Durable State

## Status
Proposed

## Context
The Universal Web Acquisition Engine needs a reliable way to manage acquisition jobs that can survive process interruptions, system restarts, and resource constraints. Based on the competitive analysis, Botasaurus lacks true job durability - when a process is interrupted, job progress is lost and may need to be restarted from scratch.

## Decision
We will implement a core job model with the following characteristics:

1. **Stable Job Identity**: Each job has a universally unique identifier (UUID) that remains constant across restarts
2. **Persistent State Storage**: Job state is stored in a durable medium (SQLite database) rather than only in memory
3. **State Machine**: Jobs progress through well-defined states: QUEUED → RUNNING → VALIDATING → SUCCEEDED/FAILED/RETRY_WAIT/NEEDS_USER
4. **Checkpointing**: Progress within acquisition operations is periodically checkpointed to allow recovery from interruption
5. **Idempotency**: Where possible, operations are designed to be idempotent to prevent duplicate work on restart
6. **Attempt Tracking**: Each execution attempt is tracked separately with its own status, timing, and resource usage
7. **Separation of Concerns**: Job definition (what to do) is separate from job execution state (progress, results)

## Consequences

### Positive
- Jobs can be recovered after process termination, system reboot, or resource constraints
- Clear visibility into job progress and failure points
- Prevents duplicate work when restarting after transient failures
- Enables resource-aware scheduling and throttling
- Provides foundation for observability and monitoring

### Negative
- Increased complexity in job management
- Storage overhead for job state and checkpoints
- Need to handle storage failures and corruption
- Potential performance impact from persistent state writes

## Implementation Plan
1. Design SQL schema for job state, attempts, and checkpoints
2. Implement job state machine with defined transitions
3. Create storage abstraction layer for persistent state
4. Implement checkpointing mechanism for long-running operations
5. Add idempotency keys where applicable
6. Create job repository interface for storage operations

## Related Decisions
- ADR-002: Discovery and Scope Policy
- ADR-003: HTTP and Browser Adapter Contracts
- ADR-004: Artifact Pipeline and Integrity Verification
- ADR-005: Plugin Architecture and Contracts

## Validation
This decision will be validated by:
- Unit tests for job state transitions
- Integration tests for job persistence and recovery
- Benchmark scenarios simulating process interruption
- Resource usage measurements for state persistence overhead

