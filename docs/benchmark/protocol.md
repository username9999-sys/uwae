# Reproducible Benchmark Protocol for Universal Web Acquisition Engine

This document specifies the benchmarking methodology for comparing Universal Web Acquisition Engine (UWAE) against Botasaurus. The protocol ensures fair, reproducible comparisons that measure actual acquisition capabilities rather than just superficial metrics.

## Benchmark Philosophy

1. **Measure what matters**: Focus on verified acquisition success, not just HTTP 200 responses
2. **Reproducibility**: Use deterministic fixtures where possible, document all variables for external tests
3. **Fair comparison**: Equivalent workloads, configurations, and resource constraints
4. **Comprehensive measurement**: Correctness, performance, resource usage, and recovery capabilities
5. **Actionable results**: Clear identification of strengths, weaknesses, and opportunities for improvement

## Benchmark Layers

### Layer 1: Component Microbenchmarks
Isolate and measure individual subsystems:
- Discovery: URL extraction from various sources
- Transfer: HTTP and browser acquisition capabilities
- Identification: Format detection accuracy
- Extraction: Plugin-based content extraction
- Orchestration: Job scheduling, concurrency, and recovery

### Layer 2: End-to-End Benchmarks
Measure complete workflows from discovery to validated output:
- Realistic acquisition scenarios
- Verified content validation
- Resource usage tracking
- Recovery capability assessment

## Benchmark Environment Requirements

### Hardware and Software Specifications
All benchmarks must record:
- **Processor**: CPU model, core count, architecture
- **Memory**: Total RAM available
- **Storage**: Disk type and available space
- **Operating System**: Name, version, kernel
- **Python**: Exact version and implementation
- **Dependencies**: Exact versions of all packages
- **Network**: Interface type, baseline latency (if applicable)
- **Browser**: Version and configuration (when relevant)

### Execution Constraints
Benchmarks must enforce:
- **Single tenant execution**: No competing processes during measurement
- **Resource limits**: Configurable CPU, memory, and I/O limits
- **Network simulation**: Optional network condition simulation (latency, bandwidth, packet loss)
- **Thermal throttling prevention**: Adequate cooling to prevent performance degradation
- **Background process minimization**: Clean system state before each benchmark run

## Measurement Methodology

### Timing Measurements
- **Wall clock time**: Total elapsed time from start to finish
- **CPU time**: Actual processor time consumed
- **I/O wait time**: Time spent waiting for input/output operations
- **Latency percentiles**: p50, p90, p95, p99 latency distributions
- **Throughput**: Operations per second, bytes per second

### Resource Measurements
- **Peak memory usage**: Maximum resident set size
- **Average memory usage**: Mean memory consumption over time
- **CPU utilization**: Percentage of available CPU used
- **Disk I/O**: Read/write bytes and operations
- **Network I/O**: Sent/received bytes and packets

### Correctness Measurements
- **Verified acquisition success**: Percentage of tasks resulting in validated correct output
- **False positive rate**: Percentage of tasks incorrectly reported as successful
- **False negative rate**: Percentage of tasks incorrectly reported as failed
- **Partial success rate**: Percentage of tasks with partially correct output
- **Data integrity verification**: Checksum validation of acquired artifacts

## Benchmark Categories

### 1. Discovery Benchmarks
Measure ability to find relevant URLs and resources:
- Link extraction accuracy from HTML documents
- Sitemap parsing completeness and accuracy
- Pagination handling effectiveness
- Canonical URL resolution and deduplication
- Robots.txt compliance and crawl delay respect
- Domain boundary enforcement
- Discovery graph construction and persistence

### 2. Acquisition Benchmarks
Measure ability to retrieve resources:
- HTTP GET/POST success rates under various conditions
- Browser-based acquisition success rates
- JavaScript rendering fidelity
- Large file transfer efficiency and correctness
- Interrupted transfer resume capability
- Range request handling
- Content streaming efficiency
- Concurrent acquisition performance
- Authentication handling
- Session persistence and recovery
- Proxy configuration and usage
- User agent rotation effectiveness
- Timeout handling and configurability

### 3. Identification Benchmarks
Measure ability to identify file formats:
- Extension-based identification accuracy
- Signature-based identification accuracy
- MIME type reconciliation effectiveness
- Extensionless file handling capability
- Misleading extension detection
- Content-based format detection
- Version detection for known formats
- Unknown format handling and reporting

### 4. Extraction Benchmarks
Measure ability to extract content from acquired resources:
- Plugin-based extraction success rate
- Format-specific extractor accuracy
- Output format fidelity
- Extraction performance and resource usage
- Extraction caching effectiveness
- Fallback extraction chain functionality
- Extraction result validation
- Provenance and metadata preservation

### 5. Resilience and Recovery Benchmarks
Measure ability to handle failures and recover:
- Network failure detection and recovery
- HTTP error handling (4xx, 5xx responses)
- Timeout handling and recovery
- DNS failure handling
- Browser crash recovery
- Process interruption recovery
- Job checkpointing and resumption
- Duplicate work prevention on restart
- Resource-aware throttling under stress
- Circuit breaker effectiveness
- Graceful degradation under resource constraints

### 6. Challenge Handling Benchmarks
Measure ability to handle anti-bot and access control measures:
- HTTP 429 rate limit detection and compliance
- Retry-After header respect
- CAPTCHA detection and handling
- Challenge classification accuracy
- User-assisted challenge workflow efficiency
- Automated challenge solving capability (where possible and authorized)
- Session preservation through challenges
- Challenge-specific retry strategies
- Access denial detection and handling
- Authentication requirement detection
- JavaScript requirement detection
- Content validation failure detection

## Benchmark Execution Procedure

### Pre-Benchmark Setup
1. Document exact environment specifications
2. Clear caches and reset state between runs
3. Verify fixture availability and integrity
4. Warm up systems if appropriate (note warm vs cold state)
5. Apply resource limits and constraints
6. Initialize monitoring and measurement tools

### Benchmark Execution
1. Execute benchmark scenario according to specification
2. Collect all specified measurements during execution
3. Record any errors, exceptions, or unexpected behavior
4. Capture detailed logs for post-analysis
5. Verify completion conditions and cleanup

### Post-Benchmark Processing
1. Validate output correctness against ground truth
2. Calculate derived metrics (percentiles, averages, etc.)
3. Resource usage aggregation and analysis
4. Error categorization and root cause analysis (where possible)
5. Comparison against baseline or control measurements
6. Preparation of benchmark result documentation

## Reporting Format

All benchmark results must include:
- Environment specification (hardware, software, configuration)
- Benchmark scenario description and ground truth
- Raw measurements and observations
- Calculated metrics and statistics
- Correctness validation results
- Resource usage summaries
- Error and failure categorization
- Comparison to baseline or control (when applicable)
- Limitations and confounding factors
- Reproduction instructions

## Statistical Significance

For performance comparisons:
- Minimum 30 iterations for stable measurements
- Report median and percentile values (not just means)
- Document variability and distribution shape
- Use appropriate statistical tests for significance claims
- Confidence intervals for reported metrics where applicable
- Outlier identification and handling strategy

