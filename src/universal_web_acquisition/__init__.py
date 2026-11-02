"""Universal Web Acquisition Engine.

A Python-first, CLI-first web acquisition engine designed to compete with Botasaurus.
"""

__title__ = "universal-web-acquisition"
__description__ = "A Python-first, CLI-first web acquisition engine"
__version__ = "0.1.0"
__author__ = "Universal Web Acquisition Engine Team"
__license__ = "MIT"
__copyright__ = "Copyright 2026 Universal Web Acquisition Engine Team"

from universal_web_acquisition.core.engine import AcquisitionEngine
from universal_web_acquisition.cli.main import main

__all__ = [
    "AcquisitionEngine",
    "main",
    "__title__",
    "__description__",
    "__version__",
    "__author__",
    "__license__",
    "__copyright__",
]
