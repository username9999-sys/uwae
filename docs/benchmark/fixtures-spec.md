# Benchmark Fixture Specification for Universal Web Acquisition Engine

This document specifies the test fixtures used for benchmarking Universal Web Acquisition Engine (UWAE) against Botasaurus. Fixtures provide deterministic, controllable test scenarios that enable reproducible comparisons.

## Fixture Philosophy

1. **Deterministic**: Same input always produces same expected output
2. **Isolatable**: Each fixture tests specific capabilities without unnecessary complexity
3. **Progressive**: Fixtures build from simple to complex scenarios
4. **Verifiable**: Clear ground truth for correctness assessment
5. **Safe**: No unauthorized access to external systems
6. **Representative**: Reflect real-world web acquisition challenges

## Fixture Categories

### A. Discovery Fixtures
Test URL and resource discovery capabilities

#### A01: Simple HTML Link Extraction
- **Description**: Basic HTML with various link types (absolute, relative, fragment)
- **Ground Truth**: Specific set of expected URLs
- **Variations**: 
  - Mixed relative/absolute URLs
  - Fragment-only links
  - Empty href attributes
  - JavaScript-generated links (should not be detected in pure HTML fixture)
- **Measurement**: Precision, recall, F1-score for link extraction

#### A02: Sitemap Parsing
- **Description**: XML sitemap index and regular sitemaps
- **Ground Truth**: Complete set of URLs declared in sitemap(s)
- **Variations**:
  - Sitemap index referencing multiple sitemaps
  - Namespaced XML elements
  - Compressed sitemaps (.xml.gz)
  - Sitemaps with lastmod, changefreq, priority fields
- **Measurement**: URL recall, parsing accuracy

#### A03: Pagination Handling
- **Description**: Series of paginated pages with next/previous links
- **Ground Truth**: Complete set of pages in the pagination sequence
- **Variations**:
  - Different pagination patterns (page numbers, infinite scroll markers)
  - Missing or broken pagination links
  - Self-referential pagination
  - Pagination with query parameters
- **Measurement**: Sequence completion rate, duplication detection

#### A04: Canonical URL Resolution
- **Description**: Pages with canonical tags, base tags, and various URL formats
- **Ground Truth**: Normalized, deduplicated set of URLs
- **Variations**:
  - HTTP vs HTTPS equivalents
  - WWW vs non-WWW domains
  - Trailing slash variations
  - URL parameter ordering differences
  - Case sensitivity variations
- **Measurement**: Canonicalization accuracy, deduplication effectiveness

#### A05: Robots.txt Compliance
- **Description**: Web server with robots.txt disallowing specific paths
- **Ground Truth**: Set of URLs that should be crawled per robots.txt rules
- **Variations**:
  - Allow vs disallow directives
  - Crawl-delay directives
  - User-agent specific rules
  - Wildcard pattern matching
- **Measurement**: Compliance rate, false positive/negative rates

#### A06: Domain Boundary Enforcement
- **Description**: Content containing links to multiple domains and subdomains
- **Ground Truth**: Set of URLs within specified domain boundaries
- **Variations**:
  - Subdomain inclusion/exclusion
  - Port number considerations
  - Protocol boundary handling (http vs https)
  - Internationalized domain names (IDN)
- **Measurement**: Boundary precision and recall

### B. Acquisition Fixtures
Test resource retrieval capabilities

#### B01: Simple HTTP GET
- **Description**: Static file served via HTTP
- **Ground Truth**: Exact byte-for-byte file content
- **Variations**:
  - Small files (<1KB)
  - Medium files (10KB-100KB)
  - Large files (>1MB)
  - Various Content-Types (text/html, application/json, image/png, etc.)
- **Measurement**: Success rate, transfer speed, integrity verification

#### B02: HTTP with Query Parameters
- **Description**: HTTP GET/POST with query string parameters
- **Ground Truth**: Response matching expected parameters
- **Variations**:
  - GET vs POST methods
  - Parameter encoding (URL vs form data)
  - Special character handling
  - Empty/null parameter values
- **Measurement**: Success rate, correct parameter handling

#### B03: HTTP Status Code Handling
- **Description**: Various HTTP status codes with appropriate responses
- **Ground Truth**: Correct handling per HTTP specifications
- **Variations**:
  - Success codes (200-299)
  - Redirection codes (300-399)
  - Client error codes (400-499)
  - Server error codes (500-599)
- **Measurement**: Correct status code interpretation and handling

#### B04: HTTP Redirect Handling
- **Description**: Chain of HTTP redirects leading to final content
- **Ground Truth**: Final destination content
- **Variations**:
  - Redirect loops (should be detected and stopped)
  - Mixed redirect types (301, 302, 303, 307, 308)
  - Cross-domain redirects
  - Redirects with query parameter preservation
- **Measurement**: Redirect chain completion, loop detection accuracy

#### B05: HTTP Authentication
- **Description**: Resources requiring various authentication schemes
- **Ground Truth**: Successful access when valid credentials provided
- **Variations**:
  - Basic authentication
  - Digest authentication
  - Bearer token authentication
  - Custom header-based authentication
- **Measurement**: Authentication success rate, credential handling security

#### B06: HTTP Content Negotiation
- **Description**: Server responding with different content types based on headers
- **Ground Truth**: Correct content type based on Accept header
- **Variations**:
  - Accept language negotiation
  - Accept encoding negotiation (gzip, brotli)
  - Custom content type negotiation
- **Measurement**: Correct content type selection and decoding

#### B07: Range Requests and Resume
- **Description**: Server supporting HTTP range requests for interrupted download recovery
- **Ground Truth**: Complete file assembled from multiple range requests
- **Variations**:
  - Single range request
  - Multiple non-overlapping range requests
  - Overlapping range requests (should use latest data)
  - Server without range request support (should fall back to full re-download)
- **Measurement**: Recovery success rate, bandwidth efficiency

#### B08: Concurrent Acquisitions
- **Description**: Multiple simultaneous acquisition requests
- **Ground Truth**: All requested resources correctly retrieved
- **Variations**:
  - Same domain vs different domains
  - Same endpoint vs different endpoints
  - Mixed priority requests
  - Resource-constrained scenarios (limited connections, bandwidth)
- **Measurement**: Throughput, fairness, resource isolation, starvation prevention

#### B09: Authentication and Session Persistence
- **Description**: Web application requiring login and maintaining session state
- **Ground Truth**: Successful access to authenticated resources post-login
- **Variations**:
  - Form-based authentication
  - Token-based authentication (JWT, session cookies)
  - Multi-step authentication flows
  - Session expiration and renewal
- **Measurement**: Login success rate, session persistence duration, authenticated access success

#### B10: JavaScript Rendering
- **Description**: Pages requiring JavaScript execution to display target content
- **Ground Truth**: Content that appears after JavaScript execution
- **Variations**:
  - Immediate execution on page load
  - Delayed execution (setTimeout, setInterval)
  - User interaction required (click, scroll)
  - AJAX/XHR content loading
  - Framework-specific rendering (React, Vue, Angular)
- **Measurement**: Rendering success rate, execution time, resource usage

### C. Identification Fixtures
Test format identification capabilities

#### C01: Extension-Based Identification
- **Description**: Files with correct extensions matching content
- **Ground Truth**: Correct format identification based on extension
- **Variations**:
  - Common formats: .html, .json, .xml, .png, .jpg, .pdf, .zip, .csv
  - Less common formats: .yaml, .toml, .ini, .sql, .log
- **Measurement**: Identification accuracy for extension-based detection

#### C02: Misleading Extensions
- **Description**: Files with extensions that don't match actual content
- **Ground Truth**: True format based on content analysis
- **Variations**:
  - HTML content with .txt extension
  - JSON content with .html extension
  - Image content with .doc extension
  - Archive content with .txt extension
- **Measurement**: Ability to detect and correct misleading extensions

#### C03: Extensionless Files
- **Description**: Files with no extension containing various formats
- **Ground Truth**: True format based on content analysis
- **Variations**:
  - Plain text files
  - JSON files
  - HTML files
  - Image files
  - Archive files
- **Measurement**: Extensionless identification accuracy

#### C04: Content-Type Header vs Actual Content
- **Description**: HTTP responses where Content-Type header doesn't match actual content
- **Ground Truth**: True format based on content analysis
- **Variations**:
  - Correct Content-Type header
  - Incorrect Content-Type header
  - Missing Content-Type header
  - Conflicting signals (extension says one thing, Content-Type another)
- **Measurement**: Ability to reconcile conflicting signals

#### C05: Signature-Based Identification
- **Description**: Files identified by binary/magic number signatures
- **Ground Truth**: Format identified by header signatures
- **Variations**:
  - PDF (%PDF- header)
  - ZIP (PK.. header)
  - PNG (‰PNG header)
  - JPEG (FF D8 FF header)
  - GIF (GIF87a/GIF89a header)
  - HTML/XML (<?xml or <!DOCTYPE or <html)
  - JSON ({ or [ at start)
- **Measurement**: Signature detection accuracy and reliability

#### C06: Version Detection
- **Description**: Formats where version information can be determined from content
- **Ground Truth**: Correct format version identification
- **Variations**:
  - PDF version in header
  - ZIP version via compression method
  - HTML version via DOCTYPE
  - SVG version via root attributes
- **Measurement**: Version detection accuracy

### D. Extraction Fixtures
Test content extraction capabilities

#### D01: HTML Text Extraction
- **Description**: HTML documents with textual content to extract
- **Ground Truth**: Plain text content excluding HTML tags
- **Variations**:
  - Nested tags
  - Inline CSS and JavaScript
  - HTML entities
  - Whitespace handling
- **Measurement**: Text extraction accuracy and fidelity

#### D02: JSONPath and XPath Extraction
- **Description**: Structured data with query-based extraction
- **Ground Truth**: Values matching specific JSONPath/XPath expressions
- **Variations**:
  - Simple field extraction
  - Nested object/array navigation
  - Filtering and predicate expressions
  - Function calls (count, sum, etc.)
- **Measurement**: Query expression accuracy and performance

#### D03: Table and List Extraction
- **Description**: HTML tables and lists with structured data
- **Ground Truth**: Structured representation of tabular data
- **Variations**:
  - Simple tables
  - Tables with headers and footers
  - Nested tables
  - Tables with merged cells (colspan/rowspan)
  - Definition lists (dl/dt/dd)
- **Measurement**: Structural extraction accuracy

#### D04: Form Data Extraction
- **Description**: HTML forms with input values to extract
- **Ground Truth**: Form field names and their values/current states
- **Variations**:
  - Text inputs
  - Checkboxes and radio buttons
  - Select dropdowns
  - File inputs
  - Hidden fields
- **Measurement**: Form state extraction accuracy

#### D05: Script and Style Extraction
- **Description**: Extracting CSS and JavaScript content from HTML
- **Ground Truth**: Exact content of script and style elements
- **Variations**:
  - Inline scripts and styles
  - External resource references
  - Mixed content security policies
  - Nonce and integrity attributes
- **Measurement**: Extraction fidelity and completeness

### E. Resilience and Recovery Fixtures
Test failure handling and recovery capabilities

#### E01: Network Failure Simulation
- **Description**: Simulated network failures during acquisition
- **Ground Truth**: Appropriate failure handling and recovery behavior
- **Variations**:
  - Connection timeout
  - Connection refused
  - DNS resolution failure
  - Packet loss simulation
  - Bandwidth throttling
- **Measurement**: Failure detection accuracy, recovery success rate

#### E02: HTTP Error Handling
- **Description**: Various HTTP error status codes
- **Ground Truth**: Appropriate error handling per specifications
- **Variations**:
  - 400 Bad Request
  - 401 Unauthorized
  - 403 Forbidden
  - 404 Not Found
  - 408 Request Timeout
  - 429 Too Many Requests
  - 500 Internal Server Error
  - 502 Bad Gateway
  - 503 Service Unavailable
  - 504 Gateway Timeout
- **Measurement**: Error classification accuracy, handling appropriateness

#### E03: Browser Crash Recovery
- **Description**: Simulated browser crashes during JavaScript execution
- **Ground Truth**: Recovery from browser state loss
- **Variations**:
  - Crash during page load
  - Crash during JavaScript execution
  - Crash after content available but before extraction
  - Multiple crashes in sequence
- **Measurement**: Crash detection accuracy, recovery success rate, state preservation

#### E04: Process Interruption Recovery
- **Description**: Simulated process termination (SIGTERM, SIGKILL) during acquisition
- **Ground Truth**: Recovery from complete process loss
- **Variations**:
  - Interruption during discovery phase
  - Interruption during acquisition phase
  - Interruption during extraction phase
  - Interruption with partial progress saved
- **Measurement**: Persistence mechanism effectiveness, recovery completeness, duplicate work prevention

#### E05: Resource Constraint Adaptation
- **Description**: Acquisition under varying resource constraints
- **Ground Truth**: Appropriate scaling back rather than failure
- **Variations**:
  - Memory-limited scenarios
  - CPU-limited scenarios
  - File descriptor-limited scenarios
  - Disk space-limited scenarios
  - Network bandwidth-limited scenarios
- **Measurement**: Graceful degradation, partial success rates, resource usage optimization

### F. Challenge Handling Fixtures
Test anti-bot and access control measure handling

#### F01: Rate Limiting (HTTP 429)
- **Description**: Server responding with 429 Too Many Requests
- **Ground Truth**: Respect of rate limiting signals and backoff behavior
- **Variations**:
  - 429 without Retry-After header
  - 429 with Retry-After header
  - 429 with varying Retry-After values
  - 429 combined with other status codes
- **Measurement**: Detection accuracy, backoff compliance, throughput fairness

#### F02: CAPTCHA and Challenge Detection
- **Description**: Pages presenting CAPTCHA or other challenges
- **Ground Truth**: Correct identification of challenge presence and type
- **Variations**:
  - Text-based CAPTCHA
  - Image-based CAPTCHA
  - reCAPTCHA variants
  - hCaptcha
  - Custom challenge mechanisms
  - JavaScript-enabled challenges
- **Measurement**: Detection accuracy, false positive/negative rates, challenge classification

#### F03: Authentication Requirement Detection
- **Description**: Pages requiring authentication (login walls)
- **Ground Truth**: Correct identification of authentication needs
- **Variations**:
  - HTTP 401 Unauthorized
  - HTTP 403 Forbidden (when auth would help)
  - Login form detection in content
  - Redirect to login page
  - Authentication cookie requirements
- **Measurement**: Detection accuracy, appropriate response planning

#### F04: JavaScript Requirement Detection
- **Description**: Content that only appears after JavaScript execution
- **Ground Truth**: Correct identification of JavaScript dependency
- **Variations**:
  - Content loaded via AJAX after initial load
  - Content revealed by user interaction
  - Content generated by client-side templating
  - Content visibility toggled by JavaScript
- **Measurement**: Detection accuracy, resource usage comparison (HTTP-only vs browser)

#### F05: Content Validation Failure
- **Description**: Successfully acquired content that doesn't match expectations
- **Ground Truth**: Correct identification of content mismatch
- **Variations**:
  - Wrong file type received
  - Corrupted file received
  - Stale or outdated content
  - Content scraping prevention measures (fake data, honey pots)
- **Measurement**: Detection accuracy, appropriate handling (retry vs abandon)

#### F06: Access Denial Handling
- **Description**: Explicitly denied access to resources
- **Ground Truth**: Correct identification and handling of access denial
- **Variations**:
  - HTTP 403 Forbidden with explicit denial messaging
  - Geographic restrictions
  - IP-based access control
  - Authentication requirement misconfiguration
  - Bot detection resulting in access denial
- **Measurement**: Detection accuracy, appropriate termination or escalation

## Fixture Implementation Guidelines

### Deterministic Fixtures (Preferred)
For local testing, implement fixtures as:
1. **Local HTTP servers**: Using Python http.server or similar
2. **Mock servers**: Programmable mock servers that return predefined responses
3. **File system fixtures**: Serving static files with controlled characteristics
4. **Network simulators**: Tools like tc (traffic control) for network condition simulation
5. **Service mocks**: Mocking external dependencies (databases, APIs, etc.)

### External Fixtures (Use with Caution)
For external testing only when:
1. **Explicit authorization** is obtained for the target
2. **Terms of service** permit automated access
3. **Rate limiting** is respected to avoid abuse
4. **No sensitive data** is collected without authorization
5. **All activity** is logged and auditable

### Ground Truth Specification
Each fixture must specify:
1. **Input**: Exact request or acquisition parameters
2. **Expected Output**: Precise definition of success
3. **Success Criteria**: Measurable conditions for determining success
4. **Failure Categories**: Specific ways the fixture can fail
5. **Resource Bounds**: Expected maximum resource consumption
6. **Determinism Notes**: Any sources of non-determinism and how they're handled

## Measurement and Reporting

### Per-Fixture Metrics
For each fixture execution, record:
- **Timestamp**: Start and end time
- **Duration**: Total execution time
- **Resource Usage**: Peak memory, average CPU, disk I/O
- **Attempt Count**: Number of acquisition attempts made
- **Success/Failure**: Final outcome classification
- **Output Fidelity**: Degree to which output matches ground truth
- **Error Details**: Any errors, exceptions, or unexpected behavior
- **Retry History**: Number and timing of retry attempts
- **Recovery Events**: Any recovery operations performed

### Aggregated Reporting
Report results as:
1. **Per-fixture summary**: Success rates, performance metrics
2. **Category averages**: Average performance across fixture types
3. **Trend analysis**: Performance changes over multiple runs
4. **Resource efficiency**: Outcomes per unit resource consumed
5. **Error breakdown**: Categorization of failures by type
6. **Recovery effectiveness**: Success rates after failure injection

## Safety and Ethics

### Authorization
- Never test against systems without explicit permission
- Respect robots.txt and terms of service
- Use authorized test targets only
- Cease testing immediately if requested by system owners

### Rate Limiting
- Implement polite delays between requests
- Respect Retry-After and similar headers
- Distribute load over time to avoid burst traffic
- Implement exponential backoff for failed requests

### Data Protection
- Never collect personally identifiable information without consent
- Securely store any test data or credentials
- Anonymize or pseudonymize data where possible
- Delete test data after benchmark completion

### System Impact
- Monitor and limit resource consumption during testing
- Avoid disrupting shared services or infrastructure
- Clean up all test artifacts after completion
- Leave systems in original or better state

