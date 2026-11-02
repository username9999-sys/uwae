# ADR-004: Artifact Pipeline and Integrity Verification

## Status
Proposed

## Context
A key differentiator for the Universal Web Acquisition Engine is the ability to treat every acquired resource as a valuable artifact, regardless of whether its format is known or extractable. This contrasts with many scrapers that focus only on extraction and discard or ignore resources they cannot process. Based on the competitive analysis, while Botasaurus acquires resources, it does not appear to have a universal artifact pipeline that preserves resources independently of extraction success.

## Decision
We will implement an artifact pipeline with the following characteristics:

### Artifact Lifecycle
1. **Acquisition**: Raw bytes are received from the transport adapter (HTTP, browser, etc.)
2. **Storage**: Raw bytes are immediately stored durably with metadata
3. **Integrity Verification**: Fixity checks (hashes) are performed and stored
4. **Identification**: Format is identified through multiple signals (extension, MIME, content signatures)
5. **Extraction**: Appropriate extractor is applied if format is known and extractor available
6. **Output**: Extracted content is stored separately with provenance links to source artifact
7. **Preservation**: Source artifact is preserved regardless of extraction success or format knowledge

### Artifact Model
Each artifact consists of:
- **Artifact ID**: Universally unique identifier (UUID)
- **Source Information**: 
  - Original URL requested
  - Final URL after redirects
  - Acquisition timestamp
  - Transport adapter used
  - HTTP status code and headers (if applicable)
- **Storage Information**:
  - Storage location (file path or object reference)
  - Byte count
  - Hash(es) (SHA-256 for integrity, optionally others for faster lookup)
  - Storage timestamp
- **Identification Information**:
  - Detected format(s) with confidence levels
  - Evidence for each format (extension match, MIME match, signature match, etc.)
  - Format identification timestamp
- **Extraction Information** (if attempted):
  - Extractor used (name and version)
  - Extraction timestamp
  - Output artifact ID(s) (if extraction produced discrete outputs)
  - Success/failure status
  - Error information (if failed)
  - Provenance linking to source artifact

### Key Principles
1. **Artifact First**: Every acquisition attempt results in a stored artifact, even if it's just the raw bytes
2. **Immutability**: Once stored, artifacts are never modified (append-only storage)
3. **Provenance**: Complete history of transformations is preserved
4. **Fixity**: Integrity is verified through cryptographic hashes
5. **Discovery**: Artifacts are discoverable by their properties (format, source URL, etc.)
6. **Longevity**: Artifacts are stored in a way that ensures long-term accessibility

### Storage Organization
Artifacts are stored in a content-addressable manner:
- Primary storage: `artifacts/{first_two_chars_of_artifact_id}/{artifact_id}.dat`
- Metadata storage: `artifacts/{first_two_chars_of_artifact_id}/{artifact_id}.meta.json`
- This provides good filesystem distribution and prevents directory bloat

## Consequences

### Positive
- No acquired data is lost due to extraction failure or unknown format
- Enables format archaeology: applying new extractors to old artifacts
- Supports reprocessing when extractors improve or new formats are supported
- Provides audit trail for compliance and debugging
- Enables storage optimization (deduplication, compression) at artifact level
- Clear separation between acquisition concerns and processing concerns

### Negative
- Increased storage requirements (raw bytes + metadata + potential extracts)
- Need for storage management policies (retention, archiving, cleanup)
- Slightly more complex API (artifact handles vs direct data access)
- Need to handle storage failures and corruption

## Implementation Plan
1. Define artifact model and metadata schema
2. Implement storage abstraction layer (local filesystem first)
3. Create artifact service for storage, retrieval, and management
4. Implement fixity verification (hashing on store and verify)
5. Build identification service with plugin-based format detectors
6. Create extraction service that coordinates with plugin registry
7. Implement artifact lifecycle management (acquisition → storage → identification → extraction)
8. Add storage optimization features (deduplication reference counting)

## Related Decisions
- ADR-001: Core Job Model and Durable State
- ADR-002: Discovery and Scope Policy
- ADR-003: HTTP and Browser Adapter Contracts
- ADR-005: Plugin Architecture and Contracts
- ADR-006: Adaptive Access Engine
- ADR-007: Session Management and Recovery

## Validation
This decision will be validated by:
- Unit tests for artifact model and storage operations
- Integration tests for complete artifact lifecycle
- Benchmark scenarios measuring artifact storage overhead and retrieval performance
- Fixity verification tests (corruption detection, hash verification)
- Provenance tracking tests (ensuring complete history is preserved)
- Storage optimization testing (deduplication effectiveness)

