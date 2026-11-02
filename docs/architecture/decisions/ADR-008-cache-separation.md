# ADR-008: Cache Separation and Invalidation Policies

## Status
Proposed

## Context
Effective caching is essential for web acquisition engine performance, but improper caching can lead to stale data, incorrect results, and wasted resources. Based on the competitive analysis, while Botasaurus has caching capabilities, it lacks sophisticated cache separation policies and intelligent invalidation strategies that distinguish between different types of cached data.

## Decision
We will implement a comprehensive caching system with the following characteristics:

### Cache Separation Principles
The engine maintains separate caches for different types of data to prevent interference and enable appropriate invalidation strategies:

1. **Transport Cache**: HTTP-level caching of responses
   - What: HTTP responses (headers, body, status codes)
   - Why: To avoid re-downloading unchanged resources
   - Invalidation: Based on HTTP cache headers (Expires, Cache-Control, ETag, Last-Modified)
   - Scope: Per-request, shared across jobs for same URLs

2. **Artifact Cache**: Storage of acquired resources
   - What: Raw byte content of acquired resources with metadata
   - Why: To avoid re-acquiring resources we've already stored
   - Invalidation: Based on content fixity (hashes) and explicit invalidation policies
   - Scope: Permanent until explicitly removed or expired by retention policy

3. **Identification Cache**: Results of format identification
   - What: Format identification results for specific content
   - Why: To avoid re-identifying the same content repeatedly
   - Invalidation: When identification algorithms improve or content changes
   - Scope: Content-addressable (based on content hash)

4. **Extraction Cache**: Results of content extraction
   - What: Extracted content from specific artifacts using specific extractors
   - Why: To avoid re-extracting content with the same extractor
   - Invalidation: When extractor improves, extractor version changes, or source artifact changes
   - Scope: Artifact-addressable (artifact ID + extractor ID + version)

5. **DNS Resolution Cache**: Resolved domain names to IP addresses
   - What: DNS lookup results
   - Why: To avoid repeated DNS lookups for the same domain
   - Invalidation: Based on TTL (Time To Live) from DNS response
   - Scope: Shared across all engine instances

6. **Connection Pool**: HTTP connection reuse
   - What: Established HTTP connections
   - Why: To avoid connection establishment overhead
   - Invalidation: Based on idle time, connection errors, or server signals
   - Scope: Per-host, shared across engine instances

### Invalidation Strategies
Each cache type implements appropriate invalidation strategies:

#### Time-Based Invalidation
- **TTL (Time To Live)**: Items expire after a set time
- **Scheduled Invalidation**: Items expire at specific times
- **Access-Based**: Items expire after certain number of accesses or period of inactivity

#### Event-Based Invalidation
- **Explicit Invalidation**: Items invalidated by explicit command or signal
- **Dependency-Based**: Items invalidated when their dependencies change
- **Resource-Based**: Items invalidated when underlying resource changes (for web resources)
- **Algorithm-Based**: Items invalidated when identification/extraction algorithms improve

#### Header-Based Invalidation (HTTP-specific)
- **Expires Header**: Expires at specified date/time
- **Cache-Control: max-age**: Expires after specified number of seconds
- **Cache-Control: s-maxage**: Shared cache max-age
- **Cache-Control: no-cache**: Requires revalidation with origin server
- **Cache-Control: no-store**: Do not cache
- **ETag/If-None-Match**: Validated with entity tags
- **Last-Modified/If-Modified-Since**: Validated with modification time

### Cache Organization
1. **Hierarchical Storage**: Different cache types use appropriate storage technologies:
   - Transport Cache: In-memory (LRU) with optional disk overflow
   - Artifact Cache: Disk-based (filesystem or object storage) for persistence
   - Identification Cache: In-memory or fast disk (content-addressable)
   - Extraction Cache: In-memory or fast disk (content-addressable)
   - DNS Cache: In-memory with TTL-based expiration
   - Connection Pool: In-memory connection objects

2. **Cache Sizing**: Each cache type has configurable size limits:
   - Maximum number of items
   - Maximum total size (bytes)
   - Maximum age of items
   - Eviction policies (LRU, LFU, FIFO, random)

3. **Cache Metrics**: Each cache tracks:
   - Hit rate (hits/(hits+misses))
   - Miss rate
   - Eviction rate
   - Size and utilization
   - Average item age

### Specialized Caching Policies
1. **Stale-While-Revalidate**: Use stale item while fetching fresh version in background
2. **Stale-If-Error**: Use stale item when origin server returns error
3. **Probationary Caching**: New items enter probationary state before full caching
4. **Adaptive Caching**: Cache size and behavior adjusts based on workload patterns
5. **Geographic Caching**: Different caches for different geographic regions (for CDN-like scenarios)

### Cache Key Generation
Cache keys are generated systematically to prevent collisions:
1. **Transport Cache Keys**: Based on normalized URL, method, headers, and body
2. **Artifact Cache Keys**: Content-addressable (hash of content)
3. **Identification Cache Keys**: Hash of content to be identified
4. **Extraction Cache Keys**: Hash of (artifact ID, extractor ID, extractor version, extraction parameters)
5. **DNS Cache Keys**: Domain name
6. **Connection Pool Keys**: Host, port, and connection properties

### Cache Warming and Preloading
Strategic cache warming improves initial performance:
1. **Predictive Warming**: Based on historical access patterns
2. **Manual Warming**: Explicitly load known important resources
3. **Seed-Based Warming**: Warm caches with seed URLs and their likely resources
4. **Dependency-Based Warming**: Warm caches with dependencies of seed resources

## Consequences

### Positive
- Appropriate caching for different data types prevents interference
- Reduced redundant acquisitions and processing
- Improved performance through intelligent reuse
- Better resource utilization through hit rate optimization
- Ability to tune caching behavior for different use cases
- Clear separation of concerns between different caching needs

### Negative
- Increased complexity in cache management
- Potential for stale data if invalidation policies are too lenient
- Potential for excessive re-fetching if policies are too strict
- Memory and disk overhead for maintaining multiple caches
- Need to tune cache sizes and policies for optimal performance

## Implementation Plan
1. Define cache interfaces and base classes for each cache type
2. Implement transport cache with HTTP-aware invalidation
3. Implement artifact cache with content-addressable storage
4. Implement identification and extraction caches with content-addressable keys
5. Implement DNS cache with TTL-based expiration
6. Implement connection pool with idle-time expiration
7. Add cache metrics collection and monitoring
8. Implement cache sizing and eviction policies (LRU, LFU, etc.)
9. Add cache warming and preloading capabilities
10. Implement cache diagnostics and inspection tools

## Related Decisions
- ADR-001: Core Job Model and Durable State
- ADR-002: Discovery and Scope Policy
- ADR-003: HTTP and Browser Adapter Contracts
- ADR-004: Artifact Pipeline and Integrity Verification
- ADR-005: Integrity Verification and Format Identification
- ADR-006: Capability Registry and Plugin Contracts
- ADR-007: Adaptive Access Assessment and Recovery
- ADR-009: Concurrency, Cancellation, and Backpressure
- ADR-010: Observability, Security, and Benchmark Methodology

## Validation
This decision will be validated by:
- Unit tests for each cache type and invalidation strategy
- Integration tests measuring cache hit rates and performance
- Benchmark scenarios comparing cached vs uncached performance
- Tests verifying correct invalidation behavior
- Memory and disk usage measurements for cache overhead
- Tests for cache warming effectiveness
- Performance tests under various workload patterns

