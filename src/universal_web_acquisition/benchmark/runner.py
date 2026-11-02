"""Benchmark runner for the Universal Web Acquisition Engine."""

import time
from typing import Any, Dict, Optional

from universal_web_acquisition import __version__
from universal_web_acquisition.core.engine import AcquisitionEngine
from universal_web_acquisition.benchmark.model import BenchmarkResult


class BenchmarkRunner:
    """Runner for benchmark scenarios."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the benchmark runner.
        
        Args:
            config_path: Optional path to configuration file
        """
        self.config_path = config_path
        self.engine = AcquisitionEngine(config_path)
        
    async def run_scenario(self, scenario_name: str, engine: str = "uwae") -> BenchmarkResult:
        """Run a benchmark scenario.
        
        Args:
            scenario_name: Name of the scenario to run
            engine: Engine to benchmark ("uwae" or "botasaurus")
            
        Returns:
            Benchmark result
        """
        start_time = time.time()
        
        try:
            if engine == "uwae":
                result = await self._run_uwae_scenario(scenario_name)
            elif engine == "botasaurus":
                result = await self._run_botasaurus_scenario(scenario_name)
            else:
                raise ValueError(f"Unknown engine: {engine}")
                
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            
            return BenchmarkResult(
                scenario_name=scenario_name,
                engine=engine,
                success=result.get("success", False),
                duration_ms=duration_ms,
                memory_bytes=result.get("memory_bytes", 0),
                error=result.get("error")
            )
        except Exception as e:
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            
            return BenchmarkResult(
                scenario_name=scenario_name,
                engine=engine,
                success=False,
                duration_ms=duration_ms,
                memory_bytes=0,
                error=str(e)
            )
    
    async def _run_uwae_scenario(self, scenario_name: str) -> Dict[str, Any]:
        """Run a scenario using the UWAE engine.
        
        Args:
            scenario_name: Name of the scenario to run
            
        Returns:
            Dictionary with result information
        """
        # This is a simplified implementation
        # In a real implementation, we would have predefined scenarios
        # and actually execute them against the engine
        
        # For now, we'll just submit a test job and wait for completion
        test_url = "https://httpbin.org/html"  # A simple test URL
        
        # Submit the job
        job_id = self.engine.submit_job(url=test_url)
        
        # Wait for completion (with timeout)
        job = self.engine.wait_for_job(job_id, timeout=30.0)
        
        # Return result
        return {
            "success": job.status == "succeeded",
            "memory_bytes": 0  # We don't measure memory in this simple implementation
        }
    
    async def _run_botasaurus_scenario(self, scenario_name: str) -> Dict[str, Any]:
        """Run a scenario using Botasaurus.

        NOT implemented — returning fake success without executing anything
        would violate the evidence-first mandate (no claims without results).
        The real differential evidence lives in the committed E-series
        harnesses (docs/benchmark/).

        Args:
            scenario_name: Name of the scenario to run

        Raises:
            NotImplementedError: always — honest failure, no fake success
        """
        raise NotImplementedError(
            "Botasaurus benchmarking is not implemented in this runner — "
            "real differential evidence lives in docs/benchmark/ (E5/E8)"
        )
