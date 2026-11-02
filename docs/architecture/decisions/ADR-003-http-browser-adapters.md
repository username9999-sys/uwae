# ADR-003: HTTP and Browser Adapter Contracts

## Status
Proposed

## Context
The acquisition engine needs to fetch web resources using different mechanisms depending on the requirements of the target resource. Based on the competitive analysis, while Botasaurus has both HTTP request (@request) and browser (@browser) capabilities, the integration between these mechanisms is tight and not easily extensible. We need a clean separation where acquisition logic is decoupled from the specific transport mechanism.

## Decision
We will implement a pluggable adapter system for resource acquisition with the following characteristics:

### Adapter Contract
All acquisition adapters must implement a common interface:

```
from typing import Protocol, AsyncIterator, Mapping, Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class AcquisitionRequest:
    url: str
    method: str = "GET"
    headers: Mapping[str, str] = None
    body: Optional[bytes] = None
    timeout_seconds: float = 30.0
    priority: int = 0  # Higher priority = processed first

@dataclass(frozen=True)
class AcquisitionResponse:
    requested_url: str
    final_url: str
    status_code: int
    headers: Mapping[str, str]
    body_stream: AsyncIterator[bytes]
    elapsed_seconds: float
    adapter_name: str
    auth_required: bool = False
    challenge_detected: bool = False
    content_length: Optional[int] = None
    content_type: Optional[str] = None

@runtime_checkable
class AcquisitionAdapter(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def capabilities(self) -> frozenset[str]: ...
    
    async def acquire(self, request: AcquisitionRequest) -> AcquisitionResponse:
        ...
    
    async def close(self) -> None:
        ...
```

### Required Adapters
1. **HTTP Adapter**: Based on httpx (with fallback to requests/aiohttp)
   - Supports: sync/async, streaming, connection pooling, proxy, HTTP/2
   - Capabilities: {"http", "sync", "async", "streaming", "pooling", "proxy"}
   
2. **Browser Adapter**: Based on Playwright (with Termux/Android considerations)
   - Supports: JavaScript execution, cookies, screenshots, DOM inspection
   - Capabilities: {"browser", "javascript", "cookies", "screenshots", "dom"}
   
3. **File Adapter**: For local file acquisition (testing/fixtures)
   - Supports: local file:// URLs
   - Capabilities: {"file", "sync"}

### Adapter Registry
Adapters are registered by capability and selected by the Adaptive Access Engine based on:
- Resource requirements (does it need JavaScript?)
- Available capabilities (what adapters can fulfill the request?)
- Historical performance (which adapter works best for this resource type?)
- Resource costs (memory, CPU, time)
- Current resource constraints (system load, battery level, etc.)

## Consequences

### Positive
- Clear separation of concerns between acquisition logic and transport mechanisms
- Easy to add new adapters (e.g., for FTP, SFTP, database queries)
- Ability to choose optimal transport per resource rather than one-size-fits-all
- Independent testing and versioning of adapters
- Clear capability negotiation prevents mismatched expectations

### Negative
- Indirection overhead (minimal, typically nanoseconds)
- Need to define and maintain adapter contracts
- Potential for capability gaps if no adapter meets requirements
- Increased complexity in adapter selection logic

## Implementation Plan
1. Define adapter contracts in Python using Protocol and dataclasses
2. Implement HTTP adapter using httpx as primary, requests as fallback
3. Implement browser adapter using Playwright (investigate Termux compatibility)
4. Implement file adapter for testing and local fixtures
5. Create adapter registry with capability-based selection
6. Implement fallback logic when preferred adapter fails
7. Add adapter metrics and health monitoring

## Related Decisions
- ADR-001: Core Job Model and Durable State
- ADR-002: Discovery and Scope Policy
- ADR-004: Artifact Pipeline and Integrity Verification
- ADR-005: Plugin Architecture and Contracts
- ADR-006: Adaptive Access Engine

## Validation
This decision will be validated by:
- Unit tests for adapter contracts and implementations
- Integration tests measuring adapter performance and correctness
- Benchmark scenarios comparing different adapters on equivalent workloads
- Capability negotiation tests ensuring correct adapter selection
- Failure scenario testing (adapter unavailability, timeouts, etc.)

