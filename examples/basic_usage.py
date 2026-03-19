"""
Basic usage of the Simudyne Pulse Python SDK.

Before running:
  1. Sign up at https://pulse.simudyne.com
  2. Create an API key from your dashboard
  3. Set your API key:
       export SIMUDYNE_API_KEY=pk_live_...
"""

from simudyne import PulseABM

client = PulseABM(api_key="YOUR_API_KEY")

# ── Discover available data ──
symbols = client.data.get_symbols(year=2024)
print("Available data:")
print(symbols)
print()

# ── L1: top of book ──
l1 = client.data.get_L1("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T09:20:00")
print("L1 (top of book):")
print(l1.head())
print()

# ── L2: full order book ──
l2 = client.data.get_L2("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T09:16:00")
print("L2 (full order book):")
print(l2.head())
print()

# ── Orders ──
orders = client.data.get_orders("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T09:20:00")
print("Orders:")
print(orders.head())
print()

# ── Trades ──
trades = client.data.get_trades("HKEX", "HSIJ4", "2024-04-02T09:15:00", "2024-04-02T10:00:00")
print("Trades:")
print(trades.head())
