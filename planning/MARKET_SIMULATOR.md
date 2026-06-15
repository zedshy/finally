# Market Simulator — Design and Implementation

The simulator generates realistic-looking stock prices using Geometric Brownian Motion (GBM) with correlated moves across tickers, optional random "event" spikes, and daily open-price tracking. It runs entirely in-process with no external dependencies.

---

## Why GBM?

Geometric Brownian Motion is the foundation of the Black-Scholes options pricing model and is the standard toy model for equity prices. It has two key properties that make simulated prices feel real:

1. **Log-normal distribution** — prices can never go negative
2. **Continuous compounding** — percentage returns are normally distributed

The discrete-time update rule (Euler-Maruyama):

```
S(t+dt) = S(t) * exp((μ - σ²/2) * dt + σ * √dt * Z)
```

Where:
- `S(t)` — current price
- `μ` — drift (annualized expected return, e.g. 0.10 for 10% p.a.)
- `σ` — volatility (annualized standard deviation, e.g. 0.30 for 30% p.a.)
- `dt` — time step in years (500 ms ≈ 1.585e-8 years)
- `Z` — standard normal random variable

For FinAlly's 500 ms update cadence, `dt = 0.5 / (252 * 6.5 * 3600) ≈ 8.5e-8` years (trading seconds per year).

---

## Correlated Moves

Independent GBM produces uncorrelated tickers — all prices wander independently. Real stocks in the same sector move together. We achieve this via **Cholesky decomposition** of a correlation matrix.

Given a target correlation matrix `Σ` (symmetric, positive-definite), decompose it as `L = chol(Σ)`. At each time step, draw a vector of independent standard normals `z ~ N(0, I)` and transform: `Z_corr = L @ z`. The resulting `Z_corr` has the desired cross-correlations.

### Default Correlation Structure

```python
# Simplified block structure
# Tech cluster: AAPL, GOOGL, MSFT, AMZN, NVDA, META — correlation ~0.65
# TSLA            — tech-adjacent, lower correlation ~0.35
# Finance cluster: JPM, V — correlation ~0.50
# Entertainment:  NFLX — low correlation with finance, medium with tech ~0.40
```

---

## Random "Events"

Every 30–90 seconds, the simulator picks a random ticker and applies a sudden ±2–5% price move. This mimics earnings surprises, analyst upgrades, or macro headlines and keeps the demo visually engaging.

---

## Daily Open Price Tracking

Each ticker stores an `open_price`, initialized to its seed price at startup. Every 24 hours (wall clock), all open prices reset to the current price. The daily change % displayed in the UI is:

```
daily_change_pct = (current_price - open_price) / open_price * 100
```

---

## Seed Prices

Approximate real-world prices as of late 2025 (simulator starting points):

| Ticker | Seed Price |
|--------|-----------|
| AAPL | $190.00 |
| GOOGL | $175.00 |
| MSFT | $415.00 |
| AMZN | $200.00 |
| TSLA | $250.00 |
| NVDA | $875.00 |
| META | $560.00 |
| JPM | $220.00 |
| V | $285.00 |
| NFLX | $700.00 |

Unknown tickers (user-added) start at $100.00 with standard GBM parameters.

---

## Full Implementation

```python
# backend/market/simulator.py

import asyncio
import math
import random
from datetime import datetime, timedelta, timezone
from typing import ClassVar

import numpy as np

from .base import MarketDataProvider, PricePoint


# ------------------------------------------------------------------ #
# Per-ticker configuration
# ------------------------------------------------------------------ #

@dataclass
class TickerConfig:
    seed_price: float
    mu: float       # annualized drift (e.g. 0.10)
    sigma: float    # annualized volatility (e.g. 0.30)


TICKER_CONFIGS: dict[str, TickerConfig] = {
    "AAPL":  TickerConfig(seed_price=190.00, mu=0.10, sigma=0.25),
    "GOOGL": TickerConfig(seed_price=175.00, mu=0.12, sigma=0.28),
    "MSFT":  TickerConfig(seed_price=415.00, mu=0.11, sigma=0.24),
    "AMZN":  TickerConfig(seed_price=200.00, mu=0.13, sigma=0.30),
    "TSLA":  TickerConfig(seed_price=250.00, mu=0.08, sigma=0.60),
    "NVDA":  TickerConfig(seed_price=875.00, mu=0.20, sigma=0.55),
    "META":  TickerConfig(seed_price=560.00, mu=0.14, sigma=0.35),
    "JPM":   TickerConfig(seed_price=220.00, mu=0.09, sigma=0.22),
    "V":     TickerConfig(seed_price=285.00, mu=0.08, sigma=0.18),
    "NFLX":  TickerConfig(seed_price=700.00, mu=0.11, sigma=0.38),
}

DEFAULT_CONFIG = TickerConfig(seed_price=100.00, mu=0.10, sigma=0.30)

# Trading seconds per year: 252 days × 6.5 hrs × 3600 s
TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600

# Correlation matrix for the 10 default tickers
# Order: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX
CORRELATION_MATRIX = np.array([
    #AAPL  GOOGL  MSFT  AMZN  TSLA  NVDA  META  JPM    V  NFLX
    [1.00,  0.68,  0.72,  0.60,  0.38,  0.62,  0.65,  0.30,  0.28,  0.42],  # AAPL
    [0.68,  1.00,  0.70,  0.65,  0.35,  0.60,  0.67,  0.28,  0.26,  0.45],  # GOOGL
    [0.72,  0.70,  1.00,  0.63,  0.36,  0.63,  0.66,  0.32,  0.30,  0.40],  # MSFT
    [0.60,  0.65,  0.63,  1.00,  0.38,  0.55,  0.62,  0.30,  0.27,  0.45],  # AMZN
    [0.38,  0.35,  0.36,  0.38,  1.00,  0.48,  0.40,  0.20,  0.18,  0.35],  # TSLA
    [0.62,  0.60,  0.63,  0.55,  0.48,  1.00,  0.58,  0.25,  0.22,  0.38],  # NVDA
    [0.65,  0.67,  0.66,  0.62,  0.40,  0.58,  1.00,  0.28,  0.25,  0.48],  # META
    [0.30,  0.28,  0.32,  0.30,  0.20,  0.25,  0.28,  1.00,  0.62,  0.22],  # JPM
    [0.28,  0.26,  0.30,  0.27,  0.18,  0.22,  0.25,  0.62,  1.00,  0.20],  # V
    [0.42,  0.45,  0.40,  0.45,  0.35,  0.38,  0.48,  0.22,  0.20,  1.00],  # NFLX
])

DEFAULT_TICKERS_ORDER = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


# ------------------------------------------------------------------ #
# Simulator implementation
# ------------------------------------------------------------------ #

class SimulatorProvider(MarketDataProvider):
    """
    GBM-based price simulator with correlated moves, event spikes, and
    daily open-price tracking. Runs entirely in-process.
    """

    UPDATE_INTERVAL: ClassVar[float] = 0.5    # seconds between ticks
    EVENT_MIN_INTERVAL: ClassVar[float] = 30  # seconds between random events
    EVENT_MAX_INTERVAL: ClassVar[float] = 90
    EVENT_MAGNITUDE: ClassVar[tuple[float, float]] = (0.02, 0.05)  # 2–5%
    OPEN_RESET_HOURS: ClassVar[float] = 24.0

    def __init__(self) -> None:
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._prev_prices: dict[str, float] = {}
        self._open_prices: dict[str, float] = {}
        self._history: dict[str, list[PricePoint]] = {}
        self._cholesky: np.ndarray | None = None      # L for default 10 tickers
        self._task: asyncio.Task | None = None
        self._event_task: asyncio.Task | None = None
        self._open_reset_task: asyncio.Task | None = None
        self._last_open_reset: datetime = datetime.now(timezone.utc)

    # ---------------------------------------------------------------- #
    # MarketDataProvider interface
    # ---------------------------------------------------------------- #

    async def start(self, tickers: list[str]) -> None:
        self._tickers = list(tickers)
        self._init_prices(self._tickers)
        self._rebuild_cholesky()

        self._task = asyncio.create_task(self._tick_loop())
        self._event_task = asyncio.create_task(self._event_loop())
        self._open_reset_task = asyncio.create_task(self._open_reset_loop())

    async def stop(self) -> None:
        for task in (self._task, self._event_task, self._open_reset_task):
            if task:
                task.cancel()
        await asyncio.gather(
            *(t for t in (self._task, self._event_task, self._open_reset_task) if t),
            return_exceptions=True,
        )

    async def get_prices(self, tickers: list[str]) -> list[PricePoint]:
        return [self._make_point(t) for t in tickers if t in self._prices]

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            cfg = TICKER_CONFIGS.get(ticker, DEFAULT_CONFIG)
            self._prices[ticker] = cfg.seed_price
            self._prev_prices[ticker] = cfg.seed_price
            self._open_prices[ticker] = cfg.seed_price
            self._history[ticker] = []
            self._tickers.append(ticker)
            self._rebuild_cholesky()

    async def remove_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            self._tickers.remove(ticker)
            self._rebuild_cholesky()
        # Retain cache entries so SSE history still works briefly

    async def get_history(self, ticker: str, limit: int = 120) -> list[PricePoint]:
        return list(self._history.get(ticker, []))[-limit:]

    # ---------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------- #

    def _init_prices(self, tickers: list[str]) -> None:
        for ticker in tickers:
            cfg = TICKER_CONFIGS.get(ticker, DEFAULT_CONFIG)
            self._prices[ticker] = cfg.seed_price
            self._prev_prices[ticker] = cfg.seed_price
            self._open_prices[ticker] = cfg.seed_price
            self._history[ticker] = []

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky decomposition whenever the ticker list changes."""
        n = len(self._tickers)
        if n == 0:
            self._cholesky = None
            return

        # Build correlation matrix for current tickers
        corr = np.eye(n)
        default_order_idx = {t: i for i, t in enumerate(DEFAULT_TICKERS_ORDER)}

        for i, ti in enumerate(self._tickers):
            for j, tj in enumerate(self._tickers):
                if i == j:
                    continue
                ii = default_order_idx.get(ti)
                jj = default_order_idx.get(tj)
                if ii is not None and jj is not None:
                    corr[i, j] = CORRELATION_MATRIX[ii, jj]
                else:
                    # Unknown tickers get low correlation with everything
                    corr[i, j] = 0.15

        # Ensure the matrix is valid (positive definite)
        try:
            self._cholesky = np.linalg.cholesky(corr)
        except np.linalg.LinAlgError:
            # Fallback: identity (no correlation)
            self._cholesky = np.eye(n)

    def _step_prices(self) -> None:
        """Advance all prices by one GBM step with cross-correlations."""
        n = len(self._tickers)
        if n == 0:
            return

        dt = self.UPDATE_INTERVAL / TRADING_SECONDS_PER_YEAR

        # Draw correlated standard normals
        z_independent = np.random.standard_normal(n)
        if self._cholesky is not None:
            z = self._cholesky @ z_independent
        else:
            z = z_independent

        for i, ticker in enumerate(self._tickers):
            cfg = TICKER_CONFIGS.get(ticker, DEFAULT_CONFIG)
            s = self._prices[ticker]
            drift = (cfg.mu - 0.5 * cfg.sigma ** 2) * dt
            diffusion = cfg.sigma * math.sqrt(dt) * z[i]
            new_price = s * math.exp(drift + diffusion)

            self._prev_prices[ticker] = s
            self._prices[ticker] = max(new_price, 0.01)  # floor at 1 cent

    def _make_point(self, ticker: str) -> PricePoint:
        price = self._prices[ticker]
        open_price = self._open_prices[ticker]
        daily_pct = ((price - open_price) / open_price * 100) if open_price else 0.0
        return PricePoint(
            ticker=ticker,
            price=round(price, 2),
            prev_price=round(self._prev_prices[ticker], 2),
            open_price=round(open_price, 2),
            timestamp=datetime.now(timezone.utc),
            daily_change_pct=round(daily_pct, 3),
        )

    def _record_history(self) -> None:
        for ticker in self._tickers:
            if ticker not in self._history:
                self._history[ticker] = []
            self._history[ticker].append(self._make_point(ticker))
            if len(self._history[ticker]) > 120:
                self._history[ticker] = self._history[ticker][-120:]

    # ---------------------------------------------------------------- #
    # Background loops
    # ---------------------------------------------------------------- #

    async def _tick_loop(self) -> None:
        """Main GBM step loop at UPDATE_INTERVAL cadence."""
        while True:
            self._step_prices()
            self._record_history()
            await asyncio.sleep(self.UPDATE_INTERVAL)

    async def _event_loop(self) -> None:
        """Random spike events — sudden 2–5% move on a random ticker."""
        while True:
            wait = random.uniform(self.EVENT_MIN_INTERVAL, self.EVENT_MAX_INTERVAL)
            await asyncio.sleep(wait)
            if not self._tickers:
                continue
            ticker = random.choice(self._tickers)
            magnitude = random.uniform(*self.EVENT_MAGNITUDE)
            direction = random.choice([-1, 1])
            self._prev_prices[ticker] = self._prices[ticker]
            self._prices[ticker] *= 1 + direction * magnitude

    async def _open_reset_loop(self) -> None:
        """Reset open prices every 24 hours to the current price."""
        while True:
            await asyncio.sleep(self.OPEN_RESET_HOURS * 3600)
            for ticker in list(self._prices):
                self._open_prices[ticker] = self._prices[ticker]
```

---

## Key Design Decisions

### Why Euler-Maruyama (not analytical)?

The analytical solution `S(t) = S(0) * exp(...)` computes the price at any future time directly but doesn't allow per-step correlation injection. The Euler-Maruyama discrete step applies the correlated random draw at every interval, which is exactly what we need.

### Why Cholesky for correlation?

Cholesky decomposition `L = chol(Σ)` transforms an uncorrelated noise vector into a correlated one with `Z = L @ z`. It is numerically stable, O(n³) to compute (n ≤ 20 tickers so this is negligible), and only needs to be recomputed when the ticker list changes.

### Why a floor at $0.01?

GBM with a very high downward spike or very high volatility can theoretically produce negative exponent values that round to zero. A floor prevents division-by-zero in daily change calculations and keeps prices displayable.

### Dynamic ticker support

`add_ticker()` seeds the new ticker from `TICKER_CONFIGS` or uses the default, then calls `_rebuild_cholesky()` to incorporate the new ticker into the correlated noise structure. The next tick loop iteration will pick it up automatically.

---

## Tuning Parameters

These constants can be exposed as environment variables if needed:

| Constant | Default | Effect |
|----------|---------|--------|
| `UPDATE_INTERVAL` | 0.5 s | Faster = more CPU, smoother sparklines |
| `EVENT_MIN_INTERVAL` | 30 s | Min gap between drama spikes |
| `EVENT_MAX_INTERVAL` | 90 s | Max gap between drama spikes |
| `EVENT_MAGNITUDE` | 2–5% | Size of random event moves |
| `OPEN_RESET_HOURS` | 24 h | How often daily % resets |
| Per-ticker `sigma` | varies | Higher = more volatile price action |

---

## Testing the Simulator

```python
# Quick sanity check — prices should drift around seed values

import asyncio
from backend.market.simulator import SimulatorProvider

async def test():
    sim = SimulatorProvider()
    await sim.start(["AAPL", "GOOGL", "TSLA"])
    await asyncio.sleep(5)
    prices = await sim.get_prices(["AAPL", "GOOGL", "TSLA"])
    for p in prices:
        print(f"{p.ticker}: ${p.price:.2f}  daily: {p.daily_change_pct:+.2f}%")
    await sim.stop()

asyncio.run(test())
```

Expected output: prices near seed values, daily change near 0% (since open was seeded at startup), correlation visible by running for several minutes and plotting.
