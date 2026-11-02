# ADR-005: Integrity Verification and Format Identification

## Status
Proposed

## Context
Ensuring the integrity of acquired resources and accurately identifying their format are critical for a trustworthy acquisition engine. Based on the competitive analysis, while Botasaurus stores acquired resources, it lacks robust, extensible mechanisms for format identification that go beyond file extensions, and integrity verification appears to be basic at best.

## Decision
We will implement a two-stage verification and identification system with the following characteristics:

### Integrity Verification
1. **Fixity Checking on Storage**: Every artifact undergoes cryptographic hashing (SHA-256) immediately upon storage
2. **Hash Storage**: Hashes are stored alongside artifact metadata in a tamper-evident manner
3. **Verification on Retrieval**: Artifacts can be verified against their stored hash on retrieval
4. **Chain of Custody**: Hash history is maintained for artifacts that undergo transformations
5. **Configurable Algorithms**: While SHA-256 is default, other algorithms (SHA-3, Blake2) can be configured

### Format Identification
1. **Multi-Stage Identification**: Format is determined through weighted evidence from multiple sources:
   - File extension (weakest evidence)
   - HTTP Content-Type header
   - Magic number/signature detection (binary file headers)
   - Content-based detection (XML/JSON parsing attempts, HTML doctype detection)
   - User-provided hints (when available)
2. **Extensible Registry**: Format identification plugins can be added without modifying core
3. **Confidence Scoring**: Each identification attempt produces a confidence score (0.0-1.0)
4. **Format Version Detection**: Where possible, format versions are identified (PDF version, HTML5 vs older, etc.)
5. **Fallback to Unknown**: When identification confidence is below threshold, format is marked as unknown
6. **Format Families**: Related formats (e.g., different PDF versions) are grouped for plugin matching

### Identification Evidence Types
Each piece of evidence includes:
- **Source**: Where the evidence came from (extension, mime, signature, content)
- **Type**: What kind of evidence (extension_match, mime_match, signature_match, content_match)
- **Value**: The detected format/value
- **Confidence**: Weight of this evidence (0.0-1.0)
- **Details**: Additional information (matched signature bytes, etc.)

### Identification Process
1. Collect all available evidence from acquisition context
2. Run each evidence through appropriate identification plugins
3. Weight evidence by source reliability (signature > content > mime > extension)
4. Calculate weighted average confidence for each candidate format
5. Select format with highest confidence above threshold (default 0.7)
6. If no format exceeds threshold, mark as unknown with evidence retained

## Consequences

### Positive
- No reliance on potentially misleading file extensions
- Ability to detect when extensions don't match content
- Confidence scoring allows for nuanced decisions
- Extensible system can adapt to new formats
- Version detection enables format-specific processing
- Integrity verification protects against data corruption and transmission errors

### Negative
- Increased processing time for identification
- Need to maintain signature database
- Potential for conflicting evidence requiring resolution logic
- Storage overhead for maintaining multiple evidence types

## Implementation Plan
1. Define identification evidence model and confidence scoring system
2. Implement signature-based identification for common formats (PDF, ZIP, PNG, JPEG, GIF, HTML, XML, JSON)
3. Implement content-based identification (XML/JSON well-formedness, HTML doctype)
4. Create identification registry and plugin interface
5. Build evidence collection and weighting system
6. Integrate with artifact pipeline (post-storage identification)
7. Add verification-on-retrieval capability
8. Implement format family grouping for plugin matching

## Related Decisions
- ADR-001: Core Job Model and Durable State
- ADR-002: Discovery and Scope Policy
- ADR-003: HTTP and Browser Adapter Contracts
- ADR-004: Artifact Pipeline and Storage
- ADR-007: Capability Registry and Plugin Contracts (general)
- ADR-009: Cache Separation and Invalidation

## Validation
This decision will be validated by:
- Unit tests for each identification method
- Integration tests for the complete identification pipeline
- Benchmark scenarios measuring identification accuracy and speed
- Tests with misleading extensions and corrupted files
- Version detection accuracy tests
- Performance impact measurements

