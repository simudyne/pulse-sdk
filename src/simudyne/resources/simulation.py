"""
Simulation Resource for the Pulse SDK.

This module provides methods for running agent-based market simulations,
tracking job status, and retrieving results.

Workflow:
    1. Submit a simulation with run() -> returns job_id and sim_ids
    2. Track progress with get_job_status(job_id)
    3. View all past jobs with get_jobs()
    4. Once complete, retrieve results with get_job_results() or get_sim_data()
"""

import io

RUN_PATH = "/simulation/run"
JOBS_PATH = "/simulation/jobs"
RESULTS_PATH = "/simulation/results"
AVAILABLE_PATH = "/simulation/data/available"
CALIBRATE_PATH = "/calibrate"

# Available market scenarios
SCENARIOS = {
    "normal": "No scenario injection - background agents only",
    "flash_crash": "Large rapid SELL depleting bid-side liquidity",
    "buy_panic": "Large rapid BUY depleting ask-side liquidity",
    "gradual_selloff": "Slow sustained SELL over an extended period",
    "trending_up": "Small steady BUY flow producing a persistent uptrend",
    "trending_down": "Small steady SELL flow producing a persistent downtrend",
}

# Scenario parameter defaults
SCENARIO_DEFAULTS = {
    "flash_crash": {
        "impact_multiplier": 22.0,
        "order_size_ratio": 0.19,
        "order_freq": "500ms",
        "start_time": "10:30:00",
    },
    "buy_panic": {
        "impact_multiplier": 22.0,
        "order_size_ratio": 0.19,
        "order_freq": "500ms",
        "start_time": "10:30:00",
    },
    "gradual_selloff": {
        "impact_multiplier": 10.0,
        "order_size_ratio": 0.05,
        "order_freq": "5s",
        "start_time": "10:30:00",
    },
    "trending_up": {
        "impact_multiplier": 5.0,
        "order_size_ratio": 0.03,
        "order_freq": "30s",
        "start_time": "10:30:00",
    },
    "trending_down": {
        "impact_multiplier": 5.0,
        "order_size_ratio": 0.03,
        "order_freq": "30s",
        "start_time": "10:30:00",
    },
}


class SimulationResource:
    """
    Run agent-based market simulations and track job status.
    
    Example workflow:
        >>> # Submit a simulation
        >>> result = client.simulation.run(
        ...     symbol="9999.HK",
        ...     cal_date="2025-09-01",
        ...     n_runs=10,
        ...     scenario="flash_crash"
        ... )
        >>> job_id = result["job_id"]
        >>> print(f"Submitted job: {job_id}")
        
        >>> # Check status
        >>> status = client.simulation.get_job_status(job_id)
        >>> print(f"Progress: {status['status_summary']}")
        >>> print(f"Complete: {status['is_complete']}")
        
        >>> # View all jobs
        >>> jobs = client.simulation.get_jobs()
        >>> print(f"Total jobs: {jobs['total']}")
    """
    
    def __init__(self, client):
        self._client = client

    def calibrate(
        self,
        symbol: str,
        cal_date: str,
        simulations: int = None,
        batch_size: int = None,
        optimize_adj_params: bool = True,
    ):
        """Trigger a model calibration run for a symbol and date.

        Starts the calibration process on the server as a background task.
        The server will run the Chiarella surrogate model calibration and
        write the resulting parameters to the calibration_params table.

        Args:
            symbol: Trading symbol (e.g., "9999.HK")
            cal_date: Calibration date in YYYY-MM-DD format
            simulations: Number of simulations to run during calibration
            batch_size: Batch size for calibration runs
            optimize_adj_params: Whether to optimise adjustment parameters (default True)

        Returns:
            dict: Contains status, symbol, and cal_date confirming the job was queued.

        Example:
            >>> client.simulation.calibrate(symbol="9999.HK", cal_date="2025-09-01")
            {'status': 'calibration_queued', 'symbol': '9999.HK', 'cal_date': '2025-09-01'}
        """
        payload = {
            "symbol": symbol,
            "cal_date": cal_date,
            "optimize_adj_params": optimize_adj_params,
        }
        if simulations is not None:
            payload["simulations"] = simulations
        if batch_size is not None:
            payload["batch_size"] = batch_size
        return self._client._request("POST", CALIBRATE_PATH, json=payload)

    def run(
        self,
        symbol: str,
        cal_date: str,
        n_runs: int = 100,
        seed: int = 42,
        step_size: int = 20000,
        scenario: str = "normal",
        scenario_params: dict = None,
        exec_algos: list = None,
        **kwargs
    ):
        """
        Submit a simulation run to be executed asynchronously.
        
        The simulation will run n_runs independent Monte Carlo samples. Each run
        produces a unique sim_id that can be used to retrieve results once complete.
        The user_id is automatically set from your API key.
        
        Args:
            symbol: Trading symbol (e.g., "9999.HK", "0005.HK")
            cal_date: Calibration date in YYYY-MM-DD format (e.g., "2025-09-01")
            n_runs: Number of independent Monte Carlo runs (default: 100)
            seed: Master random seed for reproducibility (default: 42)
            step_size: Simulation step size in microseconds (default: 20000)
            scenario: Market scenario to simulate. Options:
                - "normal": No scenario injection (default)
                - "flash_crash": Large rapid SELL depleting bid-side liquidity
                - "buy_panic": Large rapid BUY depleting ask-side liquidity
                - "gradual_selloff": Slow sustained SELL over extended period
                - "trending_up": Small steady BUY producing uptrend
                - "trending_down": Small steady SELL producing downtrend
            scenario_params: Override scenario defaults. Keys:
                - impact_multiplier (float): Total volume as multiple of resting liquidity
                - order_size_ratio (float): Child order size as fraction of liquidity
                - order_freq (str): Child order spacing (e.g., "500ms", "5s", "30s")
                - start_time (str): Time to begin orders (e.g., "10:30:00")
            exec_algos: List of execution algorithm configs. Each dict must have "type"
                and algo-specific parameters. Supported types:
                - "twap": Time-weighted average price
                - "vwap": Volume-weighted average price
                See documentation for full parameter list.
            **kwargs: Additional model parameters:
                - p_sigma (float): Price noise sigma
                - ft_kappa (float): Fundamental trader mean-reversion speed
                - mt_beta (float): Market maker beta
                - mt_gamma (float): Market maker gamma
                - mt_hf_beta (float): HF market maker beta
                - mt_hf_gamma (float): HF market maker gamma
                - dpx_adjustment (float): Decimal price adjustment
                - dt_touch_adjustment (float): Touch adjustment
                - cal_param_hash (str): Calibration parameter hash
                
        Returns:
            dict: Submission result containing:
                - job_id (str): Unique job identifier for tracking
                - queued_sim_ids (list): List of simulation IDs that will be run
                - run_offset (int): Starting run index
                - n_runs (int): Number of runs queued
                
        Example - Basic run:
            >>> result = client.simulation.run(
            ...     symbol="9999.HK",
            ...     cal_date="2025-09-01",
            ...     n_runs=10
            ... )
            >>> print(result["job_id"])
            
        Example - Flash crash scenario:
            >>> result = client.simulation.run(
            ...     symbol="9999.HK",
            ...     cal_date="2025-09-01",
            ...     n_runs=50,
            ...     scenario="flash_crash",
            ...     scenario_params={
            ...         "start_time": "11:00:00",
            ...         "impact_multiplier": 15.0
            ...     }
            ... )
            
        Example - With TWAP execution algo:
            >>> result = client.simulation.run(
            ...     symbol="9999.HK",
            ...     cal_date="2025-09-01",
            ...     n_runs=20,
            ...     exec_algos=[{
            ...         "type": "twap",
            ...         "order_size": 50000,
            ...         "horizon_mins": 60,
            ...         "start_time": "09:30:00"
            ...     }]
            ... )
        """
        payload = {
            "symbol": symbol,
            "cal_date": cal_date,
            "n_runs": n_runs,
            "seed": seed,
            "step_size": step_size,
            "scenario": scenario,
        }
        
        if scenario_params:
            payload["scenario_params"] = scenario_params
        if exec_algos:
            payload["exec_algos"] = exec_algos
            
        payload.update(kwargs)
        
        return self._client._request("POST", RUN_PATH, json=payload)

    def get_jobs(self):
        """
        Get all simulation jobs submitted by the authenticated user.
        
        Returns a list of jobs with their associated simulation IDs. Use this
        to find job IDs for past runs or to see what simulations are pending.
        
        Returns:
            dict: Contains:
                - jobs (list): List of job objects, each with:
                    - job_id (str): Unique job identifier
                    - sim_ids (list): List of simulation IDs in this job
                    - created_at (str): Timestamp when job was submitted
                - total (int): Total number of jobs
                
        Example:
            >>> result = client.simulation.get_jobs()
            >>> print(f"You have {result['total']} jobs")
            >>> 
            >>> for job in result["jobs"]:
            ...     print(f"Job {job['job_id']}: {len(job['sim_ids'])} simulations")
            ...     print(f"  Created: {job['created_at']}")
        """
        return self._client._request("GET", JOBS_PATH)

    def get_job_status(self, job_id: str):
        """
        Get the status of all simulations in a job.
        
        Use this to track simulation progress. Each simulation in the job goes
        through states: queued -> running -> completed (or error).
        
        Args:
            job_id: The job ID from run() or get_jobs()
            
        Returns:
            dict: Job status containing:
                - job_id (str): The job identifier
                - total_simulations (int): Number of simulations in the job
                - status_summary (dict): Count by status (e.g., {"running": 2, "completed": 8})
                - is_complete (bool): True if all simulations are completed
                - has_errors (bool): True if any simulation failed
                - simulations (list): Individual simulation statuses with:
                    - sim_id (str): Simulation identifier
                    - status (str): Current status (queued/running/completed/error)
                    - error_message (str): Error details if failed
                    - symbol_id (str): Full symbol identifier
                    - timestamp (str): Last status update time
                    
        Example - Check if job is done:
            >>> status = client.simulation.get_job_status("2103533f15ab0893")
            >>> if status["is_complete"]:
            ...     print("All simulations finished!")
            ... else:
            ...     print(f"Progress: {status['status_summary']}")
                    
        Example - Poll for completion:
            >>> import time
            >>> 
            >>> result = client.simulation.run(symbol="9999.HK", cal_date="2025-09-01", n_runs=10)
            >>> job_id = result["job_id"]
            >>> 
            >>> while True:
            ...     status = client.simulation.get_job_status(job_id)
            ...     print(f"Status: {status['status_summary']}")
            ...     
            ...     if status["is_complete"]:
            ...         print("Done!")
            ...         break
            ...     elif status["has_errors"]:
            ...         print("Some simulations failed")
            ...         break
            ...     
            ...     time.sleep(30)  # Check every 30 seconds
        """
        return self._client._request("GET", f"{JOBS_PATH}/{job_id}/status")
    
    @staticmethod
    def list_scenarios():
        """
        List available market scenarios and their descriptions.
        
        Returns:
            dict: Scenario names mapped to descriptions
            
        Example:
            >>> scenarios = client.simulation.list_scenarios()
            >>> for name, desc in scenarios.items():
            ...     print(f"{name}: {desc}")
        """
        return SCENARIOS.copy()
    
    @staticmethod
    def get_scenario_defaults(scenario: str):
        """
        Get default parameters for a scenario.
        
        Args:
            scenario: Scenario name (e.g., "flash_crash")
            
        Returns:
            dict: Default parameter values, or empty dict for "normal"
            
        Example:
            >>> defaults = client.simulation.get_scenario_defaults("flash_crash")
            >>> print(defaults)
            {'impact_multiplier': 22.0, 'order_size_ratio': 0.19, ...}
        """
        return SCENARIO_DEFAULTS.get(scenario, {}).copy()

    def get_job_results(self, job_id: str):
        """
        Get aggregated results for all simulations in a job.
        
        Returns params, metrics, and available files for each completed simulation.
        
        Args:
            job_id: The job ID from run() or get_jobs()
            
        Returns:
            dict: Contains:
                - job_id (str): The job identifier
                - total_simulations (int): Total simulations in job
                - completed (int): Number of completed simulations
                - simulations (list): Per-simulation results with:
                    - sim_id (str): Simulation identifier
                    - status (str): Completion status
                    - available_files (list): Files available for download
                    - params (dict): Simulation parameters
                    - metrics (dict): Result metrics
                    
        Example:
            >>> results = client.simulation.get_job_results(job_id)
            >>> for sim in results["simulations"]:
            ...     if sim["status"] == "completed":
            ...         print(f"{sim['sim_id']}: {sim['metrics']}")
        """
        return self._client._request("GET", f"{JOBS_PATH}/{job_id}/results")

    def list_sim_files(self, sim_id: str):
        """
        List available files for a specific simulation.
        
        Args:
            sim_id: The simulation ID
            
        Returns:
            dict: Contains:
                - sim_id (str): The simulation identifier
                - files (list): List of available filenames
                - has_sim_data (bool): Whether sim_data.parquet exists
                - has_params (bool): Whether params.json exists
                - has_results (bool): Whether results.json exists
                - has_mid_price (bool): Whether mid_price_by_min.parquet exists
                - has_exec_schedule (bool): Whether exec_schedule.parquet exists
                - has_schedule_by_min (bool): Whether schedule_by_min.parquet exists
                
        Example:
            >>> files = client.simulation.list_sim_files(sim_id)
            >>> print(f"Available: {files['files']}")
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/files")

    def get_sim_params(self, sim_id: str):
        """
        Get simulation parameters for a specific simulation.
        
        Args:
            sim_id: The simulation ID
            
        Returns:
            dict: Simulation parameters including:
                - sim_id (str)
                - calibration_params (dict)
                - scenario_params (dict)
                - exec_algo_params (dict)
                - sim_params (dict)
                
        Example:
            >>> params = client.simulation.get_sim_params(sim_id)
            >>> print(f"Scenario: {params['scenario_params']['scenario_name']}")
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/params")

    def get_sim_metrics(self, sim_id: str):
        """
        Get result metrics for a specific simulation.
        
        Args:
            sim_id: The simulation ID
            
        Returns:
            dict: Simulation result metrics
            
        Example:
            >>> metrics = client.simulation.get_sim_metrics(sim_id)
            >>> print(metrics)
        """
        return self._client._request("GET", f"{RESULTS_PATH}/{sim_id}/metrics")

    def get_sim_data(self, sim_id: str, filename: str = "sim_data.parquet"):
        """
        Download simulation data as a Polars DataFrame.
        
        Args:
            sim_id: The simulation ID
            filename: File to download. Options:
                - "sim_data.parquet": Full simulation output (LOB + orders)
                - "mid_price_by_min.parquet": Mid-price by minute
                - "exec_schedule.parquet": Execution schedule (if algo)
                - "schedule_by_min.parquet": Algo schedule by minute (if algo)
                
        Returns:
            polars.DataFrame: The simulation data
            
        Example:
            >>> df = client.simulation.get_sim_data(sim_id)
            >>> print(df.shape)
            >>> print(df.head())
            
            >>> # Get mid-price data
            >>> mid_df = client.simulation.get_sim_data(sim_id, "mid_price_by_min.parquet")
        """
        import polars as pl
        
        url = f"{self._client.base_url}{RESULTS_PATH}/{sim_id}/data/{filename}"
        response = self._client.session.get(url)
        
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise Exception(f"API Error ({response.status_code}): {detail}")
        
        return pl.read_parquet(io.BytesIO(response.content))
