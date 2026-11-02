"""Centralized config loader for UWAE (P8).

Dipilih plain pydantic ``BaseModel`` (bukan ``pydantic_settings``):
``pydantic_settings`` TIDAK terpasang di device ini, dan menambah dependensi
baru untuk membaca env var sendiri adalah solusi yang lebih ringan daripada
memaksa dependensi baru ke pyproject.

Load order (later overrides earlier):
1. Default values (hardcoded in schema)
2. YAML file (``--config`` / ``uwae.yaml``)
3. Environment variables (``UWAE_`` flat / ``UWAE__section__field`` nested)
4. CLI flags (highest priority — merged by caller with ``merge_cli_overrides``)

Skema divalidasi pydantic. Satu sumber kebenaran dipakai bersama adapter CLI
(``UWAEConfig``) dan engine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

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
    "env_to_nested",
]


class TransportConfig(BaseModel):
    """Transport layer configuration."""

    timeout_seconds: float = Field(default=30.0, ge=0.1)
    user_agent: str = Field(default="UniversalWebAcquisitionEngine/0.3.0")
    # Priority order: curl_cffi > httpx > requests
    preferred_adapters: List[str] = Field(
        default_factory=lambda: ["curl_cffi", "httpx", "requests"]
    )
    # Per-adapter overrides (merged with defaults)
    adapter_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class CacheConfig(BaseModel):
    """Response cache configuration."""

    enabled: bool = Field(default=False)
    max_entries: int = Field(default=1000, ge=0)
    max_body_bytes: int = Field(default=10 * 1024 * 1024, ge=0)  # 10 MB
    # Only cache GET responses with 2xx status
    cache_only_get_2xx: bool = Field(default=True)


class RetryConfig(BaseModel):
    """Retry policy configuration."""

    max_retries: int = Field(default=3, ge=0)
    base_backoff_seconds: float = Field(default=1.0, ge=0.0)
    max_backoff_seconds: float = Field(default=60.0, ge=0.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    # Per-reason retry budget (P2)
    retry_budget_per_reason: Dict[str, int] = Field(default_factory=dict)


class BrowserConfig(BaseModel):
    """Browser automation configuration."""

    enabled: bool = Field(default=True)
    headless: bool = Field(default=True)
    # CDP connection timeout
    connect_timeout_seconds: float = Field(default=30.0, ge=1.0)
    # Page load timeout
    page_load_timeout_seconds: float = Field(default=30.0, ge=1.0)
    # JS render wait
    js_render_wait_seconds: float = Field(default=10.0, ge=0.0)
    # Keep-alive mode
    keep_alive: bool = Field(default=False)
    keep_alive_idle_timeout_seconds: float = Field(default=300.0, ge=0.0)
    # Profile directory
    profile_dir: Optional[str] = Field(default=None)


class SessionConfig(BaseModel):
    """Session management configuration."""

    enabled: bool = Field(default=True)
    cookie_jar_path: Optional[str] = Field(default=None)
    session_ttl_seconds: float = Field(default=3600.0, ge=60.0)
    # Auto-recovery on auth expiry
    auto_recover: bool = Field(default=True)


class ShutdownConfig(BaseModel):
    """Graceful shutdown configuration."""

    # SIGTERM/SIGINT handling
    handle_signals: bool = Field(default=True)
    # Max time to wait for current job to finish
    max_wait_seconds: float = Field(default=30.0, ge=0.0)
    # Checkpoint interval during shutdown
    checkpoint_interval_seconds: float = Field(default=5.0, ge=0.5)


class ArtifactConfig(BaseModel):
    """Artifact storage configuration."""

    base_dir: str = Field(default="artifacts")
    # Integrity verification on read
    verify_integrity: bool = Field(default=True)
    # Max artifact size before streaming write
    stream_threshold_bytes: int = Field(default=10 * 1024 * 1024, ge=0)


class UWAEConfig(BaseModel):
    """Main UWAE configuration — single source of truth.

    Sengaja plain ``BaseModel`` + loader eksplisit: ``pydantic_settings``
    tidak ada di device ini, dan env-var handling yang eksplisit membuat
    urutan override terlihat di satu fungsi ``load_config`` — bukan
    disembunyikan di framework yang tidak terpasang.
    """

    transport: TransportConfig = Field(default_factory=TransportConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    shutdown: ShutdownConfig = Field(default_factory=ShutdownConfig)
    artifact: ArtifactConfig = Field(default_factory=ArtifactConfig)

    # Logging
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="text")  # text | json

    # Discovery / crawling
    max_urls: int = Field(default=100, ge=1)
    max_depth: int = Field(default=5, ge=0)
    same_origin_only: bool = Field(default=True)
    respect_robots_txt: bool = Field(default=True)

    # Concurrency
    max_concurrency: int = Field(default=4, ge=1)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v_upper = v.upper()
        if v_upper not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid log level: {v}")
        return v_upper

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        if v not in {"text", "json"}:
            raise ValueError(f"Invalid log format: {v}")
        return v


# Prefix untuk env var — dipakai juga CLI (auto_envvar_prefix) supaya
# satu baris env var yang sama mengisi config DAN flag CLI.
ENV_PREFIX = "UWAE_"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge dict bersarang; override menang atas base tanpa memutasi."""
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _convert_value(value: str) -> Any:
    """Best-effort type conversion for env var values."""
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if (value.startswith("[") and value.endswith("]")) or (
        value.startswith("{") and value.endswith("}")
    ):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _section_fields() -> Dict[str, List[str]]:
    """Nama field setiap section config (transport, cache, retry, ...).

    Section dideklarasikan dengan ``Field(default_factory=...)``, sehingga
    ``meta.default`` adalah ``PydanticUndefined`` — BUKAN instance model.
    Mengandalkan ``meta.default`` saja membuat daftar section selalu kosong
    dan pemetaan env var flat ke section gagal total. Karena itu factory
    dipanggil untuk mendapatkan instance nyata, baru field-nya diambil.
    """
    sections: Dict[str, List[str]] = {}
    for name, meta in UWAEConfig.model_fields.items():
        instance = None
        if isinstance(meta.default, BaseModel):
            instance = meta.default
        elif meta.default_factory is not None:
            try:
                candidate = meta.default_factory()
            except TypeError:
                candidate = None
            if isinstance(candidate, BaseModel):
                instance = candidate
        if instance is not None:
            sections[name] = list(type(instance).model_fields)
    return sections


def env_to_nested(env_vars: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Ubah env var ``UWAE_...`` jadi dict bersarang.

    Bentuk yang dikenal:

    - ``UWAE_LOG_LEVEL=DEBUG``              -> ``{"log_level": "DEBUG"}``
    - ``UWAE_MAX_CONCURRENCY=8``            -> ``{"max_concurrency": 8}``
    - ``UWAE__transport__timeout_seconds=5`` -> ``{"transport": {"timeout_seconds": 5}}``
    - ``UWAE_TRANSPORT_TIMEOUT_SECONDS=5``  -> ``{"transport": {"timeout_seconds": 5}}``

    Bentuk flat (tanpa ``__``) dicocokkan ke nama field top-level lebih dulu,
    lalu ke field di dalam tiap section — supaya pemakai tidak perlu
    menghafal mana yang nested dan mana yang tidak.

    Env var bernama asing yang tidak cocok field mana pun diabaikan diam-diam:
    nama milik komponen lain (mis. ``UWAE_E20_RUNS``) tidak boleh membuat
    loader gagal — itu akan merusak seluruh CLI.
    """
    env = dict(os.environ) if env_vars is None else dict(env_vars)
    nested: Dict[str, Any] = {}
    top_fields = set(UWAEConfig.model_fields)
    sections = _section_fields()
    for raw_key, raw_value in env.items():
        if not raw_key.startswith(ENV_PREFIX):
            continue
        key = raw_key[len(ENV_PREFIX):]
        if not key:
            continue
        value = _convert_value(raw_value)

        if "__" in key:
            # Bentuk nested eksplisit: section__field.
            # Setiap bagian di-strip underscore-nya: ``UWAE__transport__timeout``
            # memotong prefix ``UWAE_`` menyisakan ``_transport__timeout``, dan
            # tanpa strip itu section-nya jadi ``_transport`` — nama yang tidak
            # cocok field mana pun dan gagal validasi. Underscore DI DALAM nama
            # (``timeout_seconds``) tetap utuh karena strip hanya menyentuh
            # ujung.
            parts = [p.strip("_").lower() for p in key.split("__") if p.strip("_")]
            if len(parts) < 2:
                continue
            target = nested
            ok = True
            for part in parts[:-1]:
                # Periksa KEADAAN key, bukan hasil ``get``: ``get(part, {})``
                # menghasilkan dict baru yang lolos isinstance, sehingga
                # cabang pembuat di bawah ini tidak pernah jalan dan
                # ``target[part]`` melempar KeyError.
                if part not in target or not isinstance(target[part], dict):
                    target[part] = {}
                target = target[part]
                if not isinstance(target, dict):
                    ok = False
                    break
            if ok and isinstance(target, dict):
                target[parts[-1]] = value
            continue

        # Bentuk flat: cocokkan ke top-level, kalau tidak ada coba tiap section
        flat = key.lower()
        if flat in top_fields:
            nested[flat] = value
            continue
        for section, fields in sections.items():
            # Bentuk flat berbentuk ``<section>_<field>`` (mis.
            # ``UWAE_TRANSPORT_TIMEOUT_SECONDS``), jadi prefix section WAJIB
            # dipotong lebih dulu. Membandingkan ``transport_timeout_seconds``
            # dengan nama field ``timeout_seconds`` tidak akan pernah cocok —
            # bandingkan sisa setelah prefix, bukan nama lengkapnya.
            prefix = section + "_"
            if flat.startswith(prefix) and flat[len(prefix):] in fields:
                nested.setdefault(section, {})[flat[len(prefix):]] = value
                break
    return nested


def yaml_to_nested(path: Path) -> Dict[str, Any]:
    """Baca YAML jadi dict; file kosong -> dict kosong."""
    import yaml

    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Config {path} bukan mapping YAML (ditemukan {type(data).__name__})"
        )
    return data


def _find_config_file(config_path: Optional[str]) -> Optional[Path]:
    """Lokasi config file: argumen eksplisit, lalu default search path."""
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file tidak ditemukan: {config_path}")
        return path
    for candidate in (
        Path.cwd() / "uwae.yaml",
        Path.cwd() / "uwae.yml",
        Path.home() / ".config" / "uwae" / "uwae.yaml",
    ):
        if candidate.exists():
            return candidate
    return None


def load_config(
    config_path: Optional[str] = None,
    env_overrides: Optional[Dict[str, str]] = None,
) -> UWAEConfig:
    """Load configuration: defaults -> YAML -> env vars.

    Args:
        config_path: Path ke file YAML. ``None`` = cari default search path.
        env_overrides: Dict override env var (dipakai test / pemanggil
            programatik). Nilainya memenangi atas file YAML.

    Returns:
        Instance ``UWAEConfig`` yang sudah tervalidasi.
    """
    merged: Dict[str, Any] = {}

    path = _find_config_file(config_path)
    if path is not None:
        merged = _deep_merge(merged, yaml_to_nested(path))

    env_nested = (
        env_to_nested(env_overrides) if env_overrides is not None else env_to_nested()
    )
    merged = _deep_merge(merged, env_nested)

    return UWAEConfig.model_validate(merged)


def merge_cli_overrides(config: UWAEConfig, **kwargs) -> UWAEConfig:
    """Merge CLI flag overrides into config (highest priority)."""
    updates = {
        key: value
        for key, value in kwargs.items()
        if value is not None and key in UWAEConfig.model_fields
    }
    if not updates:
        return config
    return UWAEConfig.model_validate(_deep_merge(config.model_dump(), updates))


def write_default_config(path: Path) -> None:
    """Tulis file config default (dengan komentar minimal)."""
    import yaml

    config = UWAEConfig()
    data = config.model_dump()

    header = (
        "# UWAE Configuration\n"
        "# Generated automatically — edit as needed\n"
        "# Load order: defaults -> this file -> UWAE_* env vars -> CLI flags\n\n"
    )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(header)
        yaml.dump(
            data, handle, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
