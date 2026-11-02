# ADR-009: Concurrency, Cancellation, and Backpressure

## Status
Proposed

## Context
Effective concurrency control is essential for web acquisition engine performance and resource management. Based on the competitive analysis, while Botasaurus has parallel processing capabilities (@task decorator + joblib), it lacks sophisticated concurrency control, cancellation handling, and backpressure mechanisms that prevent resource exhaustion and ensure system stability under load.

## Decision
We will implement a comprehensive concurrency and resource management system with the following characteristics:

### Concurrency Model
The engine uses a hybrid concurrency model appropriate for different types of work:

1. **Job-Level Concurrency**: Multiple jobs can be processed concurrently
   - Limited by configurable maximum concurrent jobs
   - Each job represents a complete acquisition workflow (discovery → acquisition → extraction → export)
   - Jobs are scheduled based on priority and resource availability

2. **Task-Level Concurrency within Jobs**: Within each job, certain operations can be concurrent
   - Discovery: Multiple URL discovery operations can run concurrently
   - Acquisition: Multiple resource acquisitions can run concurrently (with host-based limits)
   - Extraction: Multiple extractions can run concurrently (CPU-bound)
   - Export: Multiple exports can run concurrently (I/O-bound)

3. **Resource-Specific Concurrency Limits**: Different resources have different concurrency limits:
   - Per-host acquisition limits (to avoid overwhelming single servers)
   - Per-domain acquisition limits (to be respectful to domains)
   - Global job limits (to prevent system overload)
   - Per-type extraction limits (CPU-intensive vs I/O-intensive extractors)
   - Browser instance limits (to prevent browser resource exhaustion)

### Concurrency Primitives
The engine uses appropriate concurrency primitives for different workloads:

1. **Async/Await (asyncio)**: For I/O-bound operations
   - HTTP acquisition (waiting for network)
   - DNS resolution
   - File I/O (reading/writing artifacts)
   - External service calls (APIs, databases, etc.)
   - Browser automation (waiting for page loads, etc.)

2. **Thread Pool**: For CPU-bound operations
   - Format identification (signature matching, content analysis)
   - Content extraction (parsing, transformation)
   - Data transformation and export
   - Image processing (if applicable)
   - Complex validation operations

3. **Process Pool**: For isolated, heavy CPU-bound work (optional)
   - Used only when explicitly configured for security or isolation
   - Higher overhead but better isolation

### Cancellation System
All operations support graceful cancellation:

1. **Hierarchical Cancellation**: Cancellation propagates downward
   - Cancelling a job cancels all its tasks
   - Cancelling a task cancels its subtasks
   - Cancellation requests are checked at well-defined points

2. **Cancellation Points**: Well-defined points where cancellation is checked:
   - Before starting each major operation (discovery, acquisition, extraction, export)
   - During long-running operations (every N bytes for streaming, every M seconds for waits)
   - Before retry attempts
   - Before resource-intensive operations
   - At natural breakpoints in algorithms

3. **Cancellation States**: Operations can be in these states relative to cancellation:
   - NOT_REQUESTED: No cancellation requested
   - REQUESTED: Cancellation requested but not yet acted upon
   - IN_PROGRESS: Operation is responding to cancellation request
   - CANCELLED: Operation has terminated due to cancellation
   - COMPLETED: Operation completed before cancellation could take effect

4. **Resource Cleanup**: On cancellation, resources are properly released:
   - Network connections are closed
   - File handles are closed
   - Database transactions are rolled back or committed
   - Memory is freed
   - Temporary files are cleaned up
   - Browser instances are closed
   - Locks are released

### Backpressure System
The engine implements backpressure to prevent overload:

1. **Load Sensing**: The engine continuously monitors:
   - Current job queue size and wait times
   - Active job count and resource utilization
   - System resource usage (CPU, memory, disk I/O, network)
   - External service response times and error rates
   - Browser resource usage and stability
   - Storage system performance and latency

2. **Backpressure Signals**: When load exceeds thresholds, the engine:
   - Decreases acceptance of new jobs
   - Increases queuing delay for new jobs
   - Reduces concurrency limits
   - Increases processing time allocations per job
   - Implements rate limiting on acquisition attempts
   - May temporarily switch to more conservative strategies

3. **Adaptive Throttling**: The engine adjusts behavior based on load:
   - Under light load: Aggressive concurrency for maximum throughput
   - At medium load: Balanced concurrency for optimal resource utilization
   - Under heavy load: Conservative concurrency to prevent overload
   - At overload: Protective mode to prevent system failure

4. **Feedback Loops**: The engine uses closed-loop control:
   - Measure current performance and resource utilization
   - Compare against targets and thresholds
   - Adjust control parameters (concurrency limits, timeouts, etc.)
   - Re-measure and adjust again

### Resource Governance
The engine implements fine-grained resource governance:

1. **Memory Governance**:
   - Per-job memory budgets
   - Global memory limits with paging to disk when necessary
   - Memory pools for reusable objects
   - Garbage collection tuning and monitoring
   - Memory leak detection and prevention

2. **CPU Governance**:
   - Per-job CPU time limits (soft and hard limits)
   - Global CPU utilization targets
   - Process priority adjustment (nice/renice on Unix)
   - Affinity settings for CPU core utilization
   - Throttling for CPU-intensive operations

3. **I/O Governance**:
   - Per-job I/O operation limits
   - Global I/O bandwidth limits
   - I/O scheduling priorities
   - Separate limits for read vs write operations
   - Sequential vs random access optimization

4. **Network Governance**:
   - Per-job network bandwidth limits
   - Per-host and per-domain connection limits
   - Connection pooling and reuse
   - DNS query rate limiting
   - Retry behavior adaptation based on network conditions

5. **File Descriptor Governance**:
   - Connection pool limits prevent fd exhaustion
   - File handle limits for artifact storage
   - Temporary file limits and cleanup
   - Database connection pooling

### Graceful Degradation
Under resource constraints, the engine degrades gracefully:

1. **Load Shedding**: Temporarily reduce service quality to maintain stability
2. **Feature Toggling**: Temporarily disable non-essential features
3. **Quality Reduction**: Reduce quality of service to conserve resources
4. **Prioritization**: Maintain high-priority work while deferring low-priority work
5. **Fallback Strategies**: Switch to more resource-efficient alternatives
6. **Communication**: Clearly signal degraded status to users and monitoring systems

## Consequences

### Positive
- System stability under varying loads
- Predictable resource consumption
- Prevention of resource exhaustion crashes
- Fair resource allocation among concurrent jobs
- Improved performance through optimal concurrency
- Better user experience under load (graceful degradation vs failure)
- Increased reliability and uptime

### Negative
- Increased complexity in resource management
- Potential for conservative behavior that underutilizes resources
- Need for careful tuning of limits and thresholds
- Additional overhead from monitoring and control systems
- Difficulty in optimizing for all workload patterns simultaneously

## Implementation Plan
1. Define resource monitoring interfaces and metrics collection
2. Implement job-level concurrency control with priority queuing
3. Implement task-level concurrency controls within jobs
4. Build resource-specific concurrency limiters (per-host, per-domain, etc.)
5. Create hierarchical cancellation system with well-defined points
6. Implement backpressure detection and adaptive throttling mechanisms
7. Build resource governors for memory, CPU, I/O, network, and file descriptors
8. Add graceful degradation mechanisms and communication systems
9. Integrate with scheduler, transport adapters, and job execution systems

## Related Decisions
- ADR-001: Core Job Model and Durable State
- ADR-002: Discovery and Scope Policy
- ADR-003: HTTP and Browser Adapter Contracts
- ADR-004: Artifact Pipeline and Integrity Verification
- ADR-005: Integrity Verification and Format Identification
- ADR-006: Capability Registry and Plugin Contracts
- ADR-007: Adaptive Access Assessment and Recovery
- ADR-008: Cache Separation and Invalidation
- ADR-010: Observability, Security, and Benchmark Methodology

## Validation
This decision will be validated by:
- Unit tests for concurrency primitives and cancellation mechanisms
- Integration tests measuring behavior under various loads
- Load testing to verify stability under high concurrency
- Stress testing to verify graceful degradation under overload
- Resource usage measurements to verify effective governance
- Performance testing to verify optimal conurrency levels
- Failure injection testing to verify cancellation and cleanup
- Long-run testing to verify absence of resource leaks

