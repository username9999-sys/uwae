"""Configuration dan graceful shutdown untuk UWAE (P8).

Modul ini adalah satu sumber kebenaran konfigurasi: schema tervalidasi
(``loader.UWAEConfig``), loader dengan urutan override eksplisit
(defaults -> YAML -> env vars -> CLI flags), dan penanganan shutdown
bersih (``shutdown.ShutdownManager``) untuk mode daemon.
"""

from universal_web_acquisition.config.loader import (
    ArtifactConfig,
    BrowserConfig,
    CacheConfig,
    RetryConfig,
    SessionConfig,
    ShutdownConfig,
    TransportConfig,
    UWAEConfig,
    load_config,
    merge_cli_overrides,
    write_default_config,
)
from universal_web_acquisition.config.shutdown import (
    ShutdownManager,
    run_with_shutdown,
    setup_logging,
)

__all__ = [
    "UWAEConfig",
    "TransportConfig",
    "CacheConfig",
    "RetryConfig",
    "BrowserConfig",
    "SessionConfig",
    "ShutdownConfig",
    "ArtifactConfig",
    "load_config",
    "merge_cli_overrides",
    "write_default_config",
    "ShutdownManager",
    "run_with_shutdown",
    "setup_logging",
]
