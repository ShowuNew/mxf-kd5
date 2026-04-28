# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the collector (runs continuously, Ctrl+C to stop)
python kd5_collector.py
```

## Architecture

Single-file Python application (`kd5_collector.py`) that polls TAIFEX (Taiwan Futures Exchange) real-time API every 15 seconds to build 5-minute candlestick bars and compute KD (Stochastic) indicators for micro futures contracts.

**Data flow:**
1. `fetch_price()` → hits TAIFEX API for live quotes on 4 symbols (MXFE6-F/M, MXFF6-F/M)
2. `get_session()` → determines day (F: 08:45–13:45) vs night (M) session suffix
3. `bar_slot()` → buckets timestamps into 5-minute slots
4. `main()` loop → aggregates OHLC per slot, calls `calc_kd()`, prints signals
5. On new slot: saves completed bar to `kd5_data.csv`; every 30 min: `git_push()` auto-commits

**Signal tiers** (printed to console in real time):

| Output | Condition |
|--------|-----------|
| `*** STRONG SIGNAL ***` | K<20 + K>D + lower wick >10pts (ratio ≥1.5×) |
| `** ENTRY SIGNAL **` | K<20 + lower wick >10pts (ratio ≥1.5×) |
| `< Waiting for reversal` | K<20 + K>D (no wick yet) |
| `<< Oversold, waiting for K>D` | K<20, K≤D |

**Key constants** (top of `kd5_collector.py`):

```python
KD_PERIOD  = 9     # Stochastic lookback period
BAR_MIN    = 5     # Candlestick size in minutes
GIT_PUSH   = True  # Auto-commit CSV to git
PUSH_EVERY = 30    # Git push interval (minutes)
```

**Persistence:** `kd5_data.csv` stores completed bars (`date, time, open, high, low, close`). The file is read on startup via `load_bars()` so KD history survives restarts.
