# Project Architecture Inventory - Universal Web Acquisition Engine

## Overall Repository Structure

### Root Level Directories
```
/
├── agentic-cli/                  # Main CLI application (TypeScript/Node.js)
├── universal-web-acquisition/    # Target project for this audit (Python)
├── website-3d/                   # 3D website project
├── website/                      # Standard website project
├── ECC/                          # Engineering guidelines and rules
├── .claude/                      # Claude Code configuration
├── bin/                          # Binary executables
├── core/                         # Core services
├── docs/                         # Documentation
├── scripts/                      # Utility scripts
└── tests/                        # Test files
```

### agentic-cli/ Structure (Existing CLI)
```
agentic-cli/
├── CLAUDE.md                     # Project-specific guidelines
├── README.md                     # Project overview
├── py/                           # Python source code
│   ├── agentic_cli/              # Main application package
│   │   ├── config.py             # Configuration handling
│   │   ├── daemon.py             # Daemon processes
│   │   ├── main.py               # Entry point
│   │   ├── output.py             # Output handling
│   │   ├── plugin_marketplace.py # Plugin management
│   │   ├── system.py             # System integration
│   │   ├── telemetry/            # Telemetry and observability
│   │   │   ├── adapters/
│   │   │   ├── context.py
│   │   │   ├── contract.py
│   │   │   └── metric.py
│   │   ├── tools.py              # Utility tools
│   │   ├── workflow_runner.py    # Job/workflow execution
│   │   └── subcommands/          # CLI subcommands
│   │       ├── audit_cmd.py
│   │       ├── config.py
│   │       ├── marketplace_cmd.py
│   │       ├── plugin_cmd.py
│   │       ├── release_cmd.py
│   │       └── update_cmd.py
│   ├── docs/                     # Documentation
│   │   └── specs/                # Technical specifications
│   ├── tests/                    # Test suite
│   │   ├── conftest.py           # pytest configuration
│   │   ├── test_marketplace_cmd.py
│   │   ├── test_plugin_cmd.py
│   │   ├── test_telemetry.py
│   │   └── test_telemetry_sink_failure.py
│   ├── pyproject.toml            # Project configuration
│   └── uv.lock                   # Dependency lock file
├── src/                          # Source files (likely Rust based on .rs extension)
│   └── mcp.rs                    # MCP server implementation
└── ...                           # Additional files and directories
```

### universal-web-acquisition/ Structure (Target Project)
```
universal-web-acquisition/
├── audit/                        # Audit materials (Botasaurus baseline)
│   ├── baseline.txt              # Baseline information
│   ├── baseline-kommit.txt       # Baseline commit hash
│   └── sumber-asli/              # Source materials
│       └── botasaurus-baseline/  # Cloned Botasaurus repository
├── docs/                         # Documentation for this project
│   ├── architecture/             # Architectural decisions
│   │   └── decisions/            # ADR (Architecture Decision Records)
│   ├── audit/                    # Audit reports
│   ├── benchmark/                # Benchmark specifications
│   └── roadmap/                  # Implementation roadmap
└── ...                           # To be developed
```

## Existing Implementations Analysis

### 1. Configuration Management
**Location:** `agentic-cli/py/agentic_cli/config.py`
**Purpose:** Handles application configuration, likely includes:
- Environment variable parsing
- Default value management
- Configuration validation
- Profile management

**Relevance to UWAE:** 
- Can potentially be adapted for UWAE configuration needs
- May need modification to support web acquisition specific settings
- Patterns for hierarchical configuration (global → project → local) may be reusable

### 2. Plugin System
**Location:** `agentic-cli/py/agentic_cli/plugin_marketplace.py`
**Purpose:** Manages plugin discovery, installation, and execution
**Relevance to UWAE:**
- Core concepts of plugin registration, lifecycle management, and sandboxing may be reusable
- Will need significant adaptation for web acquisition specific plugin types (transport, extractor, etc.)
- Marketplace concept may be overkill for initial UWAE implementation

### 3. Telemetry and Observability
**Location:** `agentic-cli/py/agentic_cli/telemetry/`
**Purpose:** Comprehensive observability system including:
- Metric collection and aggregation
- Context propagation
- Contract definitions
- Adapter patterns for different sinks

**Relevance to UWAE:**
- Highly relevant for UWAE observability requirements
- Contract patterns and adapter architecture may be directly applicable
- Metric aggregation windows and sampling strategies may be reusable
- Will need adaptation for web acquisition specific metrics (acquisition rates, challenge classification accuracy, etc.)

### 4. Workflow and Job Processing
**Location:** `agentic-cli/py/agentic_cli/workflow_runner.py`
**Purpose:** Executes workflows and manages job processing
**Relevance to UWAE:**
- Job state management patterns may be informative
- Workflow execution engine concepts may be adaptable
- Will need significant modification for web acquisition specific job types (discovery, acquisition, extraction, etc.)
- Concurrency and cancellation handling may provide useful patterns

### 5. CLI Framework and Subcommands
**Location:** `agentic-cli/py/agentic_cli/subcommands/`
**Purpose:** Implements CLI command structure
**Relevance to UWAE:**
- Command pattern implementation may be reusable
- Argument parsing and validation patterns may be applicable
- Help text and error handling patterns may be transferable
- Will need completely new command set for UWAE (audit, benchmark, run, etc.)

### 6. Daemon and System Integration
**Location:** `agentic-cli/py/agentic_cli/daemon.py` and `system.py`
**Purpose:** Background process management and system integration
**Relevance to UWAE:**
- Process lifecycle management patterns may be useful
- Signal handling and graceful shutdown patterns may be applicable
- Will need adaptation for UWAE specific daemon requirements (scheduler, recovery processes, etc.)

## Naming Conventions and Patterns

### Python Naming (in agentic-cli)
- Modules: snake_case (e.g., `plugin_marketplace.py`)
- Classes: PascalCase (e.g., `PluginMarketplace`)
- Functions and variables: snake_case
- Constants: UPPER_SNAKE_CASE
- Files: descriptive names with clear purpose

### TypeScript/JavaScript Patterns (inferred)
- Based on file extensions and project structure, appears to use modern TypeScript
- Likely follows similar naming conventions to Python components

### Configuration Patterns
- Uses `.env` files for environment variables
- Configuration objects with validation
- Profile-based configuration management

## Dependency Management

### Primary Mechanism
- `pyproject.toml` for project configuration and dependencies
- `uv.lock` for locked dependencies (using uv package manager)
- Standard Python packaging conventions

### Observed Dependencies (from pyproject.toml in agentic-cli)
```
[project]
dependencies = [
    "click",                    # CLI framework
    "rich",                     # Rich text formatting
    "pyyaml",                   # YAML parsing
    "python-dotenv",            # Environment variable loading
    # ... (truncated for brevity)
]

[project.optional-dependencies]
dev = [
    "pytest",                   # Testing
    "ruff",                     # Linting/formatting
    # ... (truncated for brevity)
]
```

## Test Patterns and Conventions

### Framework
- pytest as primary testing framework
- conftest.py for shared fixtures and configuration
- Test discovery follows standard pytest conventions

### Test Organization
- Tests organized by module/component
- Test files named `test_<module>.py`
- Use of fixtures for setup/teardown
- Parametrized tests for multiple scenarios

## Compatibility Requirements

### Python Version
- Based on shebangs and syntax, appears to target Python 3.8+
- No explicit version constraints observed in initial scan

### Platform Support
- Primary development appears to be on Linux (based on file paths and tooling)
- Cross-platform considerations likely present but not explicitly detailed
- Termux Android compatibility would require explicit testing and potential modifications

## Gaps and Opportunities for UWAE

### Reusable Components
1. **Configuration system patterns** - Can be adapted for UWAE settings management
2. **Telemetry architecture** - Highly relevant for UWAE observability needs
3. **Plugin system concepts** - Core ideas may be adaptable for UWAE plugin architecture
4. **CLI framework patterns** - Command structure and argument parsing may be reusable
5. **Workflow execution concepts** - Job processing patterns may inform UWAE scheduler

### Components Requiring New Implementation
1. **Web-specific acquisition logic** - HTTP clients, browser automation, etc.
2. **Discovery engines** - Link extraction, sitemap parsing, etc.
3. **Adaptive access systems** - Challenge detection, strategy planning, etc.
4. **Artifact management** - Raw storage, integrity verification, etc.
5. **Format identification and extraction plugins** - Core to UWAE functionality
6. **Benchmarking framework** - Specialized for web acquisition performance testing

## Recommendations for Reuse vs. New Build

### Strong Candidates for Adaptation
1. Telemetry and observability systems
2. Configuration management patterns
3. CLI command framework basics
4. Plugin lifecycle management concepts

### Requiring Significant Modification
1. Workflow/job processing systems (too specific to current use case)
2. Existing daemon implementations (different process requirements)

### Requiring Complete New Implementation
1. Web acquisition core (HTTP/browser adapters)
2. Discovery engines
3. Adaptive access systems
4. Artifact pipelines
5. Plugin systems for web-specific functions (transport, extractors, etc.)
6. Benchmarking framework

