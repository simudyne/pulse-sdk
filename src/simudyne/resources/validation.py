"""
Validation Resource for the Pulse SDK.

This module provides methods for validating simulation quality by comparing
simulated LOB data against historical data using distributional metrics,
impact response analysis, and FID scores.

Workflow:
    1. Submit a validation job with run() -> returns job_id
    2. Poll status with get_job(job_id) or use run_pipeline() for blocking
    3. View results including distances and plots
    4. List past jobs with list_jobs()
"""

import time
import base64


RUN_PATH = "/validation/run"
JOBS_PATH = "/validation/jobs"


class ValidationResource:
    def __init__(self, client):
        self._client = client

    def run(
        self,
        symbol: str,
        date: str,
        sim_ids: list[str],
        ticksize: float = 1.0,
        run_metrics: bool = True,
        run_impact: bool = False,
        run_fid: bool = False,
        n_levels: int = 10,
        rescale_volumes: bool = True,
        lot_size: int = 1,
    ) -> dict:
        """Submit a validation job.

        Compares simulation output against historical market data using
        distributional distance metrics (L1, Wasserstein), impact response
        curves, and FID scores.

        Historical data is fetched automatically from GCS based on symbol and date.
        Simulation data is fetched from each sim_id's sim_data.parquet in GCS.

        Args:
            symbol: Trading symbol (e.g. "700.HK")
            date: Calibration date in YYYY-MM-DD format (e.g. "2025-09-01")
            sim_ids: List of simulation IDs to validate (max 25)
            ticksize: Tick size for the symbol
            run_metrics: Compute L1/Wasserstein distributional distances
            run_impact: Compute impact response curves
            run_fid: Compute Frechet Inception Distance
            n_levels: Number of L2 book levels to use
            rescale_volumes: Multiply simulated L2 size columns by lot_size
            lot_size: Lot size multiplier for volume rescaling

        Returns:
            dict with job_id, status, message
        """
        payload = {
            "symbol": symbol,
            "date": date,
            "sim_ids": sim_ids,
            "ticksize": ticksize,
            "config": {
                "run_metrics": run_metrics,
                "run_impact": run_impact,
                "run_fid": run_fid,
                "n_levels": n_levels,
                "rescale_volumes": rescale_volumes,
                "lot_size": lot_size,
            },
        }
        return self._client._request("POST", RUN_PATH, json=payload)

    def get_job(self, job_id: str) -> dict:
        """Get validation job status and results.

        Args:
            job_id: The job ID returned by run()

        Returns:
            dict with:
            - status: "pending", "running", "completed", or "failed"
            - distances: dict of {metric: {l1: [...], w: [...]}} (when completed)
            - fid_scores: list of floats (when completed and run_fid=True)
            - plots: list of {name, content_base64} (when completed)
            - metadata: dict with run parameters
            - error: error message (when failed)
        """
        return self._client._request("GET", f"{JOBS_PATH}/{job_id}")

    def list_jobs(self, limit: int = 50) -> dict:
        """List validation jobs for the current user.

        Args:
            limit: Max number of jobs to return (default 50, max 200)

        Returns:
            dict with jobs list and total count
        """
        return self._client._request("GET", JOBS_PATH, params={"limit": limit})

    def run_pipeline(
        self,
        symbol: str,
        date: str,
        sim_ids: list[str],
        ticksize: float = 1.0,
        run_metrics: bool = True,
        run_impact: bool = False,
        run_fid: bool = False,
        n_levels: int = 10,
        poll_interval: float = 3.0,
        timeout: float = 600.0,
    ) -> dict:
        """Submit a validation job and block until it completes.

        Combines run() + polling get_job() into a single call.
        Prints progress to stderr.

        Args:
            symbol: Trading symbol (e.g. "700.HK")
            date: Calibration date in YYYY-MM-DD format
            sim_ids: List of simulation IDs to validate (max 25)
            ticksize: Tick size for the symbol
            run_metrics: Compute L1/Wasserstein distributional distances
            run_impact: Compute impact response curves
            run_fid: Compute Frechet Inception Distance
            n_levels: Number of L2 book levels to use
            poll_interval: Seconds between status checks (default 3)
            timeout: Max seconds to wait (default 600)

        Returns:
            dict with full validation results (distances, plots, metadata)

        Raises:
            RuntimeError: If the validation job fails
            TimeoutError: If the job doesn't complete within timeout
        """
        import sys


        job = self.run(
            symbol=symbol,
            date=date,
            sim_ids=sim_ids,
            ticksize=ticksize,
            run_metrics=run_metrics,
            run_impact=run_impact,
            run_fid=run_fid,
            n_levels=n_levels,
        )
        job_id = job["job_id"]
        print(f"Validation job submitted: {job_id}", file=sys.stderr)

        start = time.time()
        while True:
            result = self.get_job(job_id)
            status = result["status"]

            if status == "completed":
                elapsed = time.time() - start
                print(f"Completed in {elapsed:.1f}s", file=sys.stderr)
                return result
            elif status == "failed":
                raise RuntimeError(f"Validation failed: {result.get('error')}")

            if time.time() - start > timeout:
                raise TimeoutError(f"Validation job {job_id} timed out after {timeout}s")

            time.sleep(poll_interval)

    def display_plots(self, result: dict):
        """Display validation plots inline in a Jupyter notebook.

        Args:
            result: The result dict from run_pipeline() or get_job()
        """
        from IPython.display import display, Image

        plots = result.get("plots", [])
        if not plots:
            print("No plots in result")
            return

        for plot in plots:
            print(f"\n--- {plot['name']} ---")
            display(Image(data=base64.b64decode(plot["content_base64"])))
