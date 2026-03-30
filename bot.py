"""
Swing Trading Bot — Alpaca Paper Trading
Strategy: RSI + EMA crossover momentum/mean-reversion hybrid
Scans S&P 500 universe, picks top setups, manages position sizing for small accounts.

Requirements:
    pip install alpaca-trade-api pandas numpy requests yfinance

Usage:
    1. Set your Alpaca paper trading API keys in config.py (or as env vars)
    2. Run manually or schedule with cron / Task Scheduler once per day after market close
       e.g. cron: 0 21 * * 1-5 /usr/bin/python3 /path/to/bot.py
"""

import os
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf
import alpaca_trade_api as tradeapi

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ALPACA_BASE_URL,
    MAX_POSITIONS,
    RISK_PER_TRADE_PCT,
    MAX_POSITION_PCT,
    RSI_PERIOD,
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    EMA_FAST,
    EMA_SLOW,
    ATR_PERIOD,
    ATR_STOP_MULTIPLIER,
    MIN_PRICE,
    MAX_PRICE,
    MIN_AVG_VOLUME,
    WATCHLIST,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Alpaca client ─────────────────────────────────────────────────────────────
def get_api():
    return tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, api_version="v2")


# ── Indicators ────────────────────────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_atr(high, low, close, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def get_indicators(ticker: str) -> dict | None:
    """Download 90 days of daily OHLCV and compute indicators. Returns None on failure."""
    try:
        df = yf.download(ticker, period="90d", interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < EMA_SLOW + 5:
            return None

        df["rsi"] = compute_rsi(df["Close"], RSI_PERIOD)
        df["ema_fast"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
        df["ema_slow"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()
        df["atr"] = compute_atr(df["High"], df["Low"], df["Close"], ATR_PERIOD)
        df["avg_vol"] = df["Volume"].rolling(20).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        return {
            "ticker": ticker,
            "close": float(last["Close"]),
            "rsi": float(last["rsi"]),
            "ema_fast": float(last["ema_fast"]),
            "ema_slow": float(last["ema_slow"]),
            "prev_ema_fast": float(prev["ema_fast"]),
            "prev_ema_slow": float(prev["ema_slow"]),
            "atr": float(last["atr"]),
            "avg_vol": float(last["avg_vol"]),
        }
    except Exception as e:
        log.warning(f"  {ticker}: data error — {e}")
        return None


# ── Signal scoring ────────────────────────────────────────────────────────────
def score_long(ind: dict) -> float:
    """
    Score a long setup 0–100.
    Combines:
      - EMA crossover (fast crosses above slow) → momentum
      - RSI in sweet spot (40–65) → not overbought, has room
      - RSI recovering from oversold → mean-reversion entry
    Returns 0 if no valid signal.
    """
    score = 0.0

    # EMA bullish crossover just happened (or fast > slow and strengthening)
    ema_cross = (ind["prev_ema_fast"] <= ind["prev_ema_slow"]) and (ind["ema_fast"] > ind["ema_slow"])
    ema_bullish = ind["ema_fast"] > ind["ema_slow"]

    if ema_cross:
        score += 40
    elif ema_bullish:
        score += 20

    # RSI momentum zone
    rsi = ind["rsi"]
    if 45 <= rsi <= 65:
        score += 30
    elif 40 <= rsi < 45 or 65 < rsi <= 70:
        score += 15
    elif RSI_OVERSOLD < rsi < 40:
        score += 25  # mean-reversion recovery bonus

    # Penalise overbought
    if rsi > RSI_OVERBOUGHT:
        score -= 30

    return max(score, 0.0)


def passes_filters(ind: dict) -> bool:
    return (
        MIN_PRICE <= ind["close"] <= MAX_PRICE
        and ind["avg_vol"] >= MIN_AVG_VOLUME
        and not np.isnan(ind["rsi"])
        and not np.isnan(ind["atr"])
    )


# ── Position sizing ───────────────────────────────────────────────────────────
def compute_shares(equity: float, price: float, atr: float) -> int:
    """
    Risk-based sizing: risk RISK_PER_TRADE_PCT of equity per trade.
    Stop = ATR_STOP_MULTIPLIER × ATR below entry.
    Also cap at MAX_POSITION_PCT of equity.
    """
    stop_distance = ATR_STOP_MULTIPLIER * atr
    if stop_distance <= 0:
        return 0
    risk_amount = equity * RISK_PER_TRADE_PCT
    shares_by_risk = int(risk_amount / stop_distance)
    max_shares = int((equity * MAX_POSITION_PCT) / price)
    shares = min(shares_by_risk, max_shares)
    return max(shares, 0)


# ── Exit logic ────────────────────────────────────────────────────────────────
def should_exit(ind: dict) -> bool:
    """Exit signal: EMA bearish cross OR RSI overbought."""
    ema_cross_down = (ind["prev_ema_fast"] >= ind["prev_ema_slow"]) and (ind["ema_fast"] < ind["ema_slow"])
    return ema_cross_down or ind["rsi"] > RSI_OVERBOUGHT


# ── Main bot logic ────────────────────────────────────────────────────────────
def run():
    log.info("=" * 60)
    log.info("Swing Bot — daily scan starting")
    api = get_api()

    # Account info
    account = api.get_account()
    equity = float(account.equity)
    cash = float(account.cash)
    log.info(f"Account equity: ${equity:,.2f} | Cash: ${cash:,.2f}")

    if account.trading_blocked:
        log.error("Account is blocked. Exiting.")
        return

    # Current positions
    positions = {p.symbol: p for p in api.list_positions()}
    log.info(f"Open positions ({len(positions)}): {list(positions.keys())}")

    # ── Step 1: Exit check on held positions ─────────────────────────────────
    log.info("── Checking exits ──")
    for symbol, pos in positions.items():
        ind = get_indicators(symbol)
        if ind is None:
            continue
        if should_exit(ind):
            qty = abs(int(float(pos.qty)))
            try:
                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="sell",
                    type="market",
                    time_in_force="day",
                )
                log.info(f"  EXIT {symbol} × {qty} @ ~${ind['close']:.2f} | RSI={ind['rsi']:.1f}")
            except Exception as e:
                log.error(f"  EXIT order failed for {symbol}: {e}")
        else:
            log.info(f"  HOLD {symbol} | RSI={ind['rsi']:.1f} | EMA diff={ind['ema_fast']-ind['ema_slow']:.2f}")

    # Refresh positions after exits
    positions = {p.symbol: p for p in api.list_positions()}
    slots_available = MAX_POSITIONS - len(positions)
    log.info(f"── Entry scan | {slots_available} slot(s) available ──")

    if slots_available <= 0:
        log.info("No slots available. Done.")
        return

    # ── Step 2: Scan watchlist for entries ────────────────────────────────────
    candidates = []
    for ticker in WATCHLIST:
        if ticker in positions:
            continue
        ind = get_indicators(ticker)
        if ind is None or not passes_filters(ind):
            continue
        s = score_long(ind)
        if s > 0:
            ind["score"] = s
            candidates.append(ind)
            log.info(f"  {ticker}: score={s:.0f} RSI={ind['rsi']:.1f} close=${ind['close']:.2f}")

    candidates.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"  {len(candidates)} candidates scored")

    # ── Step 3: Submit entry orders ───────────────────────────────────────────
    orders_placed = 0
    for ind in candidates:
        if orders_placed >= slots_available:
            break

        # Re-fetch account cash before each order
        account = api.get_account()
        cash = float(account.cash)
        equity = float(account.equity)

        ticker = ind["ticker"]
        shares = compute_shares(equity, ind["close"], ind["atr"])
        cost = shares * ind["close"]

        if shares < 1:
            log.info(f"  SKIP {ticker}: 0 shares computed (equity too small or ATR too large)")
            continue
        if cost > cash * 0.95:
            log.info(f"  SKIP {ticker}: cost ${cost:.2f} exceeds available cash ${cash:.2f}")
            continue

        try:
            api.submit_order(
                symbol=ticker,
                qty=shares,
                side="buy",
                type="market",
                time_in_force="day",
            )
            log.info(f"  BUY {ticker} × {shares} @ ~${ind['close']:.2f} | score={ind['score']:.0f} | cost≈${cost:.2f}")
            orders_placed += 1
        except Exception as e:
            log.error(f"  BUY order failed for {ticker}: {e}")

    log.info(f"Done. {orders_placed} order(s) placed.")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
