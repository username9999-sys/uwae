# ADR-002: Discovery and Scope Policy

## Status
Proposed

## Context
Effective web acquisition requires intelligent discovery of resources to acquire. The discovery process must balance completeness with efficiency, respecting site boundaries and avoiding unnecessary resource consumption. Based on the competitive analysis, while Botasaurus has sitemap parsing and link extraction capabilities, it lacks sophisticated discovery policies and scope management.

## Decision
We will implement a discovery subsystem with the following characteristics:

1. **Multi-Source Discovery**: Ability to discover URLs from multiple sources:
   - Direct URL lists (seed URLs)
   - HTML link extraction (anchor tags, area tags, etc.)
   - Sitemap parsing (XML sitemaps and sitemap indexes)
   - Structured data (JSON-LD, microdata, RDFa)
   - RSS/Atom feeds
   - API endpoints (when documented)

2. **Configurable Scope Policies**: Discovery is constrained by configurable policies:
   - Domain boundaries (include/exclude specific domains and subdomains)
   - URL path patterns (include/exclude based on path patterns)
   - URL query parameter filtering
   - File extension filtering
   - Maximum depth from seed URLs
   - Maximum number of URLs to discover
   - URL deduplication strategies (exact, domain-normalized, path-normalized)

3. **Discovery Graph**: Maintains relationships between discovered URLs:
   - Source URL (where the link was found)
   - Link type (hyperlink, form action, redirect, etc.)
   - Discovery timestamp
   - Contextual information (link text, surrounding content)

4. **Prioritization and Scheduling**: Discovered URLs are prioritized based on:
   - Source authority (seed URLs > sitemaps > embedded links)
   - Link context (navigation links > footer links > comment links)
   - Historical success rates (for rediscovery)
   - Resource type priority (HTML > images > documents > etc.)
   - User-defined priority weights

5. **Politeness and Compliance**: Discovery respects site policies:
   - Robots.txt parsing and compliance
   - Crawl-delay respect
   - Rate limiting per domain
   - Concurrent connection limits per domain
   - User agent identification

## Consequences

### Positive
- More intelligent and efficient discovery than brute-force URL lists
- Respectful crawling that minimizes burden on target sites
- Flexible policy system adaptable to different acquisition goals
- Discovery graph enables understanding of site structure and relationships
- Prioritization focuses acquisition efforts on most valuable resources first

### Negative
- Increased complexity in discovery subsystem
- Storage requirements for discovery graph
- Need to keep robots.txt and sitemap caches fresh
- Potential for over-constraining discovery if policies are too strict

## Implementation Plan
1. Create discovery source interfaces (URL list, HTML parser, sitemap parser, etc.)
2. Implement scope policy engine with configurable rules
3. Build discovery graph data structure with persistence capabilities
4. Develop prioritization and scheduling algorithms
5. Integrate robots.txt parsing and compliance
6. Create discovery API for feeding URLs to acquisition engine

## Related Decisions
- ADR-001: Core Job Model and Durable State
- ADR-003: HTTP and Browser Adapter Contracts
- ADR-004: Artifact Pipeline and Integrity Verification
- ADR-006: Adaptive Access Engine

## Validation
This decision will be validated by:
- Unit tests for each discovery source
- Integration tests for scope policy enforcement
- Benchmark scenarios measuring discovery precision and recall
- Robots.txt compliance testing
- Discovery graph accuracy and usefulness measurements

