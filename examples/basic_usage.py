"""
Basic usage of the Simudyne Pulse Python SDK.

Before running:
  1. Sign up at https://pulse.simudyne.com
  2. Create an API key from your dashboard
  3. Set your API key:
       export SIMUDYNE_API_KEY=pk_live_...
"""

import time
from simudyne import PulseABM

client = PulseABM(api_key="YOUR_API_KEY")

# ── Profile ───────────────────────────────────────────────────────────────────

profile = client.profile.get()
print("Profile:", profile)

usage = client.profile.usage()
print("Usage this month:", usage)


# ── Discover available data ───────────────────────────────────────────────────

catalog = client.data.get_available()

# Filter to sessions that are ready to simulate
complete = [r for r in catalog if r["status"] == "complete"]
print(f"\n{len(complete)} sessions available")

# Pick a symbol and date
symbol   = complete[0]["name"]
cal_date = complete[0]["date"]
print(f"Using: {symbol}  {cal_date}")


# ── Run a simulation ──────────────────────────────────────────────────────────

result = client.simulation.run(
    symbol=symbol,
    cal_date=cal_date,
    n_runs=10,
    scenario="normal",
)
job_id = result["job_id"]
print(f"\nSubmitted job: {job_id}")
print(f"Queued sim IDs: {result['queued_sim_ids']}")


# ── Poll for completion ───────────────────────────────────────────────────────

print("\nWaiting for simulations to complete...")
while True:
    status = client.simulation.get_job_status(job_id)
    summary = status["status_summary"]
    print(f"  {summary}")
    if status["is_complete"]:
        print("All simulations complete!")
        break
    if status["has_errors"]:
        print("Some simulations failed:", summary)
        break
    time.sleep(15)


# ── Retrieve results ──────────────────────────────────────────────────────────

job_results = client.simulation.get_job_results(job_id)
print(f"\nCompleted: {job_results['completed']}/{job_results['total_simulations']}")

for sim in job_results["simulations"]:
    if sim["status"] == "complete":
        print(f"\nsim_id: {sim['sim_id']}")
        print("  files:", sim["available_files"])
        print("  metrics:", sim["metrics"])


# ── Download sim data as a DataFrame ─────────────────────────────────────────

first_complete = next(
    s for s in job_results["simulations"] if s["status"] == "complete"
)
sim_id = first_complete["sim_id"]

df = client.simulation.get_sim_data(sim_id, "mid_price_by_min.parquet")
print(f"\nMid-price data: {df.shape[0]} rows")
print(df.head())
