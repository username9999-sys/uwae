"""Tes config loader + graceful shutdown (P8).

Yang diuji di sini:
- loader: defaults, YAML, env var (flat dan nested), urutan override, dan
  penolakan nilai tidak valid — bukan "loader jalan" tapi "loader benar";
- teardown logging: handler ke stderr, logger UWAE tidak jadi root, dan
  propagasi dimatikan supaya log tidak bercampur ke stdout JSON;
- shutdown: sinyal set stop event, job context melacak job aktif, dan
  checkpoint callback tetap dipanggil saat shutdown.
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

from universal_web_acquisition.config.loader import (
    ShutdownConfig,
    UWAEConfig,
    env_to_nested,
    load_config,
    merge_cli_overrides,
    write_default_config,
)


class TestDefaults:
    def test_defaults_load_without_file_or_env(self):
        c = load_config(config_path=None, env_overrides={})
        assert c.transport.timeout_seconds == 30.0
        assert c.transport.user_agent == "UniversalWebAcquisitionEngine/0.3.0"
        assert c.log_level == "INFO"
        assert c.log_format == "text"
        assert c.max_concurrency == 4

    def test_retry_budget_defaults_empty(self):
        c = load_config(config_path=None, env_overrides={})
        assert c.retry.retry_budget_per_reason == {}


class TestEnvVarMapping:
    def test_flat_top_level(self):
        c = load_config(
            config_path=None,
            env_overrides={"UWAE_LOG_LEVEL": "DEBUG", "UWAE_MAX_CONCURRENCY": "8"},
        )
        assert c.log_level == "DEBUG"
        assert c.max_concurrency == 8

    def test_flat_into_section_strips_section_prefix(self):
        # Bentuk flat berbentuk <section>_<field> — prefix section WAJIB
        # dipotong. Tanpa itu, "transport_timeout_seconds" tidak pernah cocok
        # dengan field "timeout_seconds".
        c = load_config(
            config_path=None,
            env_overrides={"UWAE_TRANSPORT_TIMEOUT_SECONDS": "12"},
        )
        assert c.transport.timeout_seconds == 12.0

    def test_nested_double_underscore(self):
        c = load_config(
            config_path=None,
            env_overrides={"UWAE__transport__timeout_seconds": "5"},
        )
        assert c.transport.timeout_seconds == 5.0

    def test_nested_strips_leading_underscore(self):
        # UWAE__transport__... memotong prefix UWAE_ menyisakan
        # _transport__... — tanpa strip, section-nya jadi _transport.
        c = load_config(
            config_path=None,
            env_overrides={"UWAE__cache__enabled": "true"},
        )
        assert c.cache.enabled is True

    def test_boolean_conversion(self):
        c = load_config(
            config_path=None,
            env_overrides={"UWAE__cache__cache_only_get_2xx": "false"},
        )
        assert c.cache.cache_only_get_2xx is False

    def test_json_dict_and_list_conversion(self):
        c = load_config(
            config_path=None,
            env_overrides={
                "UWAE__retry__retry_budget_per_reason": '{"timeout": 2}',
                "UWAE__transport__preferred_adapters": '["curl_cffi"]',
            },
        )
        assert c.retry.retry_budget_per_reason == {"timeout": 2}
        assert c.transport.preferred_adapters == ["curl_cffi"]

    def test_unknown_env_var_is_ignored_not_fatal(self):
        # Env var milik komponen lain (mis. UWAE_E20_RUNS milik harness
        # benchmark) tidak boleh membuat loader gagal — itu merusak CLI.
        c = load_config(
            config_path=None,
            env_overrides={"UWAE_E20_RUNS": "30", "UWAE_GARBAGE_VAR": "x"},
        )
        assert c.transport.timeout_seconds == 30.0

    def test_env_beats_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text("transport:\n  timeout_seconds: 99\n", encoding="utf-8")
            c = load_config(
                config_path=str(path),
                env_overrides={"UWAE__transport__timeout_seconds": "7"},
            )
            assert c.transport.timeout_seconds == 7.0

    def test_env_to_nested_maps_all_sections(self):
        nested = env_to_nested(
            {
                "UWAE_LOG_LEVEL": "INFO",
                "UWAE__transport__timeout_seconds": "5",
                "UWAE_TRANSPORT_USER_AGENT": "custom-agent",
            }
        )
        assert nested["log_level"] == "INFO"
        assert nested["transport"]["timeout_seconds"] == 5.0
        assert nested["transport"]["user_agent"] == "custom-agent"


class TestYamlFile:
    def test_yaml_values_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text(
                "log_level: DEBUG\nmax_concurrency: 6\ntransport:\n"
                "  timeout_seconds: 3.5\n",
                encoding="utf-8",
            )
            c = load_config(config_path=str(path), env_overrides={})
            assert c.log_level == "DEBUG"
            assert c.max_concurrency == 6
            assert c.transport.timeout_seconds == 3.5

    def test_missing_explicit_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config(config_path="/nonexistent/uwae.yaml", env_overrides={})

    def test_non_mapping_yaml_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text("- just\n- a\n- list\n", encoding="utf-8")
            with pytest.raises(ValueError, match="bukan mapping"):
                load_config(config_path=str(path), env_overrides={})

    def test_empty_yaml_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text("", encoding="utf-8")
            c = load_config(config_path=str(path), env_overrides={})
            assert c.max_concurrency == 4


class TestValidation:
    def test_invalid_log_level_rejected(self):
        with pytest.raises(ValueError):
            UWAEConfig(log_level="VERBOSE")

    def test_invalid_log_format_rejected(self):
        with pytest.raises(ValueError):
            UWAEConfig(log_format="xml")

    def test_negative_max_concurrency_rejected(self):
        with pytest.raises(ValueError):
            UWAEConfig(max_concurrency=0)


class TestCliOverrides:
    def test_merge_cli_overrides_none_keeps_config(self):
        base = UWAEConfig()
        assert merge_cli_overrides(base, log_level=None) is base

    def test_merge_cli_overrides_wins_over_file_and_env(self):
        base = load_config(config_path=None, env_overrides={"UWAE_LOG_LEVEL": "DEBUG"})
        merged = merge_cli_overrides(base, log_level="ERROR", max_concurrency=9)
        assert merged.log_level == "ERROR"
        assert merged.max_concurrency == 9

    def test_merge_ignores_unknown_keys(self):
        base = UWAEConfig()
        # Field tak dikenal (di luar model_fields) diabaikan: bukan masuk ke
        # config, bukan juga membuat crash — peta penuh yang dikirim tidak
        # diketahui pemanggil.
        merged = merge_cli_overrides(base, not_a_field=1)
        assert not hasattr(merged, "not_a_field")
        assert merged.model_dump() == base.model_dump()


class TestWriteDefault:
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "default.yaml"
            write_default_config(path)
            assert path.exists()
            reloaded = load_config(config_path=str(path), env_overrides={})
            original = UWAEConfig()
            assert reloaded.model_dump() == original.model_dump()


class TestLoggingSetup:
    """Regresi: log tidak boleh meninggalkan stdout.

    Sebelum perbaikan, handler dipasang di root logger dan menulis ke stdout.
    Itu merusak kontrak ``uwae acquire --json`` (12 test CLI runtuh karena
    satu baris log muncul sebelum JSON). Dua jaminan yang diuji di sini:

    - tulisan milik UWAE hanya muncul di stderr;
    - handler root logger TIDAK disentuh — pemanggil (pytest, aplikasi host)
      punya hak penuh atas root logger.
    """

    def _emit(self) -> None:
        logging.getLogger("universal_web_acquisition.core.job_worker").info(
            "Job x succeeded"
        )

    def test_uwae_log_writes_to_stderr_not_stdout(self):
        import io
        from unittest import mock

        from universal_web_acquisition.config.shutdown import setup_logging

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with mock.patch("sys.stdout", stdout_buf), mock.patch(
            "sys.stderr", stderr_buf
        ):
            setup_logging("INFO", "text")
            self._emit()
        assert stdout_buf.getvalue() == ""
        assert "Job x succeeded" in stderr_buf.getvalue()

    def test_root_logger_handlers_untouched(self):
        from universal_web_acquisition.config.shutdown import setup_logging

        before = list(logging.getLogger().handlers)
        try:
            setup_logging("DEBUG", "json")
            assert logging.getLogger().handlers == before
        finally:
            setup_logging("INFO", "text")

    def test_uwae_logger_does_not_propagate(self):
        from universal_web_acquisition.config.shutdown import setup_logging

        try:
            setup_logging("INFO", "text")
            assert logging.getLogger(
                "universal_web_acquisition"
            ).propagate is False
        finally:
            setup_logging("INFO", "text")

    def test_json_format_is_parseable(self):
        import io
        from unittest import mock

        from universal_web_acquisition.config.shutdown import setup_logging

        stderr_buf = io.StringIO()
        try:
            with mock.patch("sys.stderr", stderr_buf):
                setup_logging("INFO", "json")
                self._emit()
            # Hanya baris JSON yang diuji: stderr juga menerima tulisan lain
            # (mis. keluaran pytest/caplog), dan memaksa "baris terakhir"
            # berarti JSON harus bersaing dengan itu. Yang diuji di sini
            # adalah "log UWAE berbentuk JSON valid", bukan "stderr hanya
            # berisi JSON".
            json_lines = [
                line
                for line in stderr_buf.getvalue().splitlines()
                if line.lstrip().startswith("{")
            ]
            assert json_lines, (
                f"tidak ada baris JSON di stderr: {stderr_buf.getvalue()!r}"
            )
            payload = json.loads(json_lines[-1])
            assert payload["message"] == "Job x succeeded"
            assert payload["level"] == "INFO"
        finally:
            setup_logging("INFO", "text")


class TestShutdownManager:
    """Graceful shutdown (P8): sinyal → job selesai → checkpoint → berhenti."""

    @staticmethod
    async def _checkpoint_probe(flag: list):
        flag.append("checkpoint")

    def test_not_shutdown_requested_initially(self):
        from universal_web_acquisition.config.shutdown import ShutdownManager

        manager = ShutdownManager(ShutdownConfig())
        assert manager.is_shutdown_requested() is False
        assert manager.is_shutdown_requested() is False

    def test_signal_marks_requested_and_runs_checkpoint(self):
        import signal
        from unittest import mock

        from universal_web_acquisition.config.shutdown import ShutdownManager

        flag: list = []

        async def checkpoint():
            await self._checkpoint_probe(flag)

        manager = ShutdownManager(
            ShutdownConfig(max_wait_seconds=0.0),
            checkpoint_fn=checkpoint,
        )
        with mock.patch("asyncio.get_running_loop"):
            asyncio.run(manager._handle_signal(signal.SIGTERM))
        assert flag == ["checkpoint"]
        assert manager.is_shutdown_requested() is True
        assert manager.stop_event.is_set()

    def test_current_job_is_tracked_and_cleared(self):
        from universal_web_acquisition.config.shutdown import ShutdownManager

        manager = ShutdownManager(ShutdownConfig())
        manager.set_current_job("job-1")
        assert manager._current_job_id == "job-1"
        manager.set_current_job(None)
        assert manager._current_job_id is None

    def test_job_context_clears_state_and_sets_stop(self):
        from universal_web_acquisition.config.shutdown import ShutdownManager

        manager = ShutdownManager(ShutdownConfig())

        async def run():
            async with manager.job_context("job-2"):
                assert manager._current_job_id == "job-2"
                assert not manager.stop_event.is_set()
            assert manager._current_job_id is None
            assert manager.stop_event.is_set()

        asyncio.run(run())

    def test_shutdown_called_twice_is_force_exit(self):
        import signal

        from universal_web_acquisition.config.shutdown import ShutdownManager

        manager = ShutdownManager(ShutdownConfig(max_wait_seconds=0.0))
        asyncio.run(manager._handle_signal(signal.SIGTERM))
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(manager._handle_signal(signal.SIGINT))
        assert excinfo.value.code == 1

    def test_stop_event_set_when_shutdown_requested(self):
        from universal_web_acquisition.config.shutdown import ShutdownManager

        manager = ShutdownManager(ShutdownConfig(max_wait_seconds=0.0))

        async def run():
            wait_task = asyncio.create_task(manager.wait_for_shutdown())
            await asyncio.sleep(0)
            import signal

            await manager._handle_signal(signal.SIGTERM)
            await asyncio.wait_for(wait_task, timeout=1.0)
            assert manager.stop_event.is_set()

        asyncio.run(run())
