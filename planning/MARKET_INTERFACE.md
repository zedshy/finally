# Market Data Interface — Unified Price Provider Design

This document defines the abstract interface and factory pattern that lets the FinAlly backend switch between the Massive API and the built-in simulator based on the `MASSIVE_API_KEY` environment variable.

---

## Design Goals

- All downstream code (SSE streaming, price cache, portfolio P&L) is **agnostic** to the data source
- Adding a new provider in the future requires only implementing the abstract base class
- The active provider is selected once at startup via a factory function
- The interface is async-native to fit cleanly in FastAPI's event loop

---

## Abstract Base Class

```python
# backend/market/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PricePoint:
    ticker: str
    price: float
    prev_price: float       # previous reading (for change direction)
    open_price: float       # day's open (for daily % change)
    timestamp: datetime
    daily_change_pct: float # (price - open_price) / open_price * 100


class MarketDataProvider(ABC):
    """
    Abstract provider for market price data.
    All implementations must be safe to call from an asyncio event loop.
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """
        Initialize the provider and begin producing data for the given tickers.
        Called once at application startup, before the SSE stream opens.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Cleanly shut down background tasks or connections."""

    @abstractmethod
    async def get_prices(self, tickers: list[str]) -> list[PricePoint]:
        """
        Return the latest PricePoint for each requested ticker.
        Tickers not yet known are silently omitted.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """
        Register a new ticker so the provider begins tracking it.
        Called when the user adds a ticker to the watchlist.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """
        Stop tracking a ticker. Already-cached data may be retained briefly.
        Called when the user removes a ticker from the watchlist.
        """

    @abstractmethod
    async def get_history(self, ticker: str, limit: int = 120) -> list[PricePoint]:
        """
        Return up to `limit` recent price points for the ticker.
        Used to seed sparklines on SSE (re)connection.
        """
```

---

## Factory Function

```python
# backend/market/factory.py

import os
from .base import MarketDataProvider
from .massive_client import MassiveProvider
from .simulator import SimulatorProvider


def create_market_provider() -> MarketDataProvider:
    """
    Returns the appropriate MarketDataProvider based on environment config.
    - MASSIVE_API_KEY set and non-empty → MassiveProvider (real data)
    - MASSIVE_API_KEY absent or empty   → SimulatorProvider (default)
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveProvider(api_key=api_key)
    return SimulatorProvider()
```

---

## Massive API Implementation

```python
# backend/market/massive_client.py

import asyncio
import os
from datetime import datetime, timezone
from massive import RESTClient

from .base import MarketDataProvider, PricePoint


# Free tier: 5 req/min → poll every 15 s
# Paid tier: adjust via env var MASSIVE_POLL_INTERVAL
DEFAULT_POLL_INTERVAL = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15"))


class MassiveProvider(MarketDataProvider):
    def __init__(self, api_key: str) -> None:
        self._client = RESTClient(api_key=api_key)
        self._tickers: set[str] = set()
        self._cache: dict[str, PricePoint] = {}
        self._history: dict[str, list[PricePoint]] = {}
        self._open_prices: dict[str, float] = {}
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._tickers = set(tickers)
        await self._seed_open_prices()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def get_prices(self, tickers: list[str]) -> list[PricePoint]:
        return [self._cache[t] for t in tickers if t in self._cache]

    async def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker)
        await self._seed_open_prices(tickers=[ticker])

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)

    async def get_history(self, ticker: str, limit: int = 120) -> list[PricePoint]:
        return list(self._history.get(ticker, []))[-limit:]

    # ------------------------------------------------------------------ #

    async def _seed_open_prices(self, tickers: list[str] | None = None) -> None:
        """Fetch previous-day close prices to use as today's open baseline."""
        targets = tickers or list(self._tickers)
        loop = asyncio.get_event_loop()
        for ticker in targets:
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda t=ticker: self._client.get_previous_close_agg(t)
                )
                if result:
                    self._open_prices[ticker] = result[0].c
            except Exception:
                self._open_prices.setdefault(ticker, 100.0)

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._fetch_and_cache()
            except Exception:
                pass  # keep running even on transient errors
            await asyncio.sleep(DEFAULT_POLL_INTERVAL)

    async def _fetch_and_cache(self) -> None:
        if not self._tickers:
            return

        loop = asyncio.get_event_loop()
        tickers = list(self._tickers)

        snapshots = await loop.run_in_executor(
            None,
            lambda: self._client.get_snapshot_all("stocks", tickers=tickers)
        )

        now = datetime.now(timezone.utc)
        for s in snapshots:
            if not s.ticker or s.day is None:
                continue

            price = s.last_trade.price if s.last_trade else s.day.c
            open_price = self._open_prices.get(s.ticker, price)
            daily_pct = ((price - open_price) / open_price * 100) if open_price else 0.0
            prev = self._cache[s.ticker].price if s.ticker in self._cache else price

            point = PricePoint(
                ticker=s.ticker,
                price=price,
                prev_price=prev,
                open_price=open_price,
                timestamp=now,
                daily_change_pct=daily_pct,
            )
            self._cache[s.ticker] = point

            if s.ticker not in self._history:
                self._history[s.ticker] = []
            self._history[s.ticker].append(point)
            if len(self._history[s.ticker]) > 120:
                self._history[s.ticker] = self._history[s.ticker][-120:]
```

---

## Price Cache (Shared Layer)

The price cache sits between the provider and the SSE endpoint. It is written by the provider's background task and read by SSE streaming. This decoupling means the SSE handler never calls the provider directly.

```python
# backend/market/cache.py

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from .base import PricePoint


@dataclass
class TickerCache:
    latest: PricePoint | None = None
    history: deque[PricePoint] = field(default_factory=lambda: deque(maxlen=120))


class PriceCache:
    """Thread-safe (asyncio) in-memory price store."""

    def __init__(self) -> None:
        self._data: dict[str, TickerCache] = {}
        self._lock = asyncio.Lock()

    async def update(self, point: PricePoint) -> None:
        async with self._lock:
            if point.ticker not in self._data:
                self._data[point.ticker] = TickerCache()
            entry = self._data[point.ticker]
            entry.latest = point
            entry.history.append(point)

    async def get_latest(self, tickers: list[str]) -> list[PricePoint]:
        async with self._lock:
            return [
                self._data[t].latest
                for t in tickers
                if t in self._data and self._data[t].latest is not None
            ]

    async def get_history(self, ticker: str) -> list[PricePoint]:
        async with self._lock:
            entry = self._data.get(ticker)
            return list(entry.history) if entry else []

    async def get_all_history(self) -> dict[str, list[PricePoint]]:
        async with self._lock:
            return {t: list(e.history) for t, e in self._data.items()}
```

---

## Application Wiring (FastAPI lifespan)

```python
# backend/main.py  (relevant excerpt)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from .market.factory import create_market_provider
from .market.cache import PriceCache
from .db import get_watchlist_tickers   # returns list[str] from SQLite

provider = create_market_provider()
cache = PriceCache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    tickers = await get_watchlist_tickers()
    await provider.start(tickers)

    # Background task: provider → cache pump
    async def pump():
        while True:
            prices = await provider.get_prices(list(active_tickers()))
            for p in prices:
                await cache.update(p)
            await asyncio.sleep(0.5)   # 500ms SSE cadence

    pump_task = asyncio.create_task(pump())
    yield
    pump_task.cancel()
    await provider.stop()


app = FastAPI(lifespan=lifespan)
```

---

## SSE Endpoint

```python
# backend/routes/stream.py

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio, json

router = APIRouter()

@router.get("/api/stream/prices")
async def stream_prices():
    async def event_generator():
        # Send history buffer on connect
        all_history = await cache.get_all_history()
        init_payload = {
            ticker: [
                {"price": p.price, "timestamp": p.timestamp.isoformat(),
                 "daily_change_pct": p.daily_change_pct}
                for p in points
            ]
            for ticker, points in all_history.items()
        }
        yield f"event: init\ndata: {json.dumps(init_payload)}\n\n"

        # Continuous price stream
        while True:
            prices = await cache.get_latest(list(active_tickers()))
            for p in prices:
                payload = {
                    "ticker": p.ticker,
                    "price": p.price,
                    "prev_price": p.prev_price,
                    "daily_change_pct": p.daily_change_pct,
                    "timestamp": p.timestamp.isoformat(),
                    "direction": "up" if p.price >= p.prev_price else "down",
                }
                yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

## File Layout

```
backend/
└── market/
    ├── __init__.py
    ├── base.py           # PricePoint dataclass + MarketDataProvider ABC
    ├── factory.py        # create_market_provider() factory
    ├── massive_client.py # MassiveProvider implementation
    ├── simulator.py      # SimulatorProvider implementation (see MARKET_SIMULATOR.md)
    └── cache.py          # PriceCache shared store
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MASSIVE_API_KEY` | _(empty)_ | If set, activates the Massive provider |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between Massive API polls |

When `MASSIVE_API_KEY` is absent or empty the simulator runs with no external dependencies.
