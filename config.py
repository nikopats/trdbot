"""
config.py — All settings for the swing trading bot.
Edit this file to customise behaviour.
"""

import os

# ── Alpaca API credentials ────────────────────────────────────────────────────
# Get your paper trading keys from: https://app.alpaca.markets/paper-trading/overview
# You can set these as environment variables or paste them directly here.
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY",    "YOUR_PAPER_API_KEY_HERE")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "YOUR_PAPER_SECRET_KEY_HERE")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"  # paper trading endpoint

# ── Position & risk management ────────────────────────────────────────────────
MAX_POSITIONS       = 4       # max simultaneous open positions (fits small account)
RISK_PER_TRADE_PCT  = 0.02    # risk 2% of equity per trade
MAX_POSITION_PCT    = 0.25    # no single position > 25% of equity
ATR_STOP_MULTIPLIER = 2.0     # stop-loss = 2 × ATR below entry

# ── Strategy parameters ───────────────────────────────────────────────────────
RSI_PERIOD    = 14
RSI_OVERSOLD  = 35
RSI_OVERBOUGHT= 72
EMA_FAST      = 9
EMA_SLOW      = 21
ATR_PERIOD    = 14

# ── Stock universe filters ────────────────────────────────────────────────────
MIN_PRICE       = 5.0         # skip penny stocks
MAX_PRICE       = 500.0       # keep affordable for small account
MIN_AVG_VOLUME  = 500_000     # liquidity filter (20-day average)

# ── Watchlist ─────────────────────────────────────────────────────────────────
# A curated list of liquid, well-known US stocks & ETFs.
# You can expand or trim this to your liking.
WATCHLIST = [
    # Broad market ETFs
    "SPY", "QQQ", "IWM", "DIA",
    # Sector ETFs
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLRE",
    # Popular large-caps
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "JPM",
    "V", "MA", "UNH", "HD", "PG", "JNJ", "XOM", "CVX", "BAC", "WFC",
    "DIS", "NFLX", "PYPL", "CRM", "ADBE", "AMD", "INTC", "QCOM",
    "COST", "WMT", "TGT", "MCD", "SBUX", "NKE", "BA", "GE", "CAT",
    "MMM", "LMT", "RTX", "PFE", "MRK", "ABBV", "TMO", "DHR",
]
