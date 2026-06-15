# Massive API (formerly Polygon.io) — Reference Guide

Massive (rebranded from Polygon.io on 30 Oct 2025) provides U.S. equity market data via REST, WebSocket, and flat-file APIs. For FinAlly we only need the REST API; specifically the snapshot endpoints that let us poll current prices for a list of tickers.

---

## Authentication

All requests require an API key passed as a Bearer token:

```
Authorization: Bearer <MASSIVE_API_KEY>
```

Alternatively, the key can be appended as a query parameter: `?apiKey=<MASSIVE_API_KEY>`.

### Base URL

```
https://api.massive.com
```

The legacy base `https://api.polygon.io` still resolves and is useful as a fallback during the transition period.

---

## Python Client

Massive ships an official Python client that wraps the REST endpoints and handles auth, pagination, and retries.

```bash
pip install -U massive
```

```python
from massive import RESTClient

client = RESTClient(api_key="YOUR_MASSIVE_API_KEY")
```

The client automatically attaches the Authorization header on every request.

---

## Rate Limits

| Plan | Price | API Calls | Data Freshness |
|------|-------|-----------|----------------|
| Free | $0 | 5 calls / min | 15-min delay |
| Stocks Starter | $29 / mo | Unlimited | 15-min delay |
| Stocks Developer | $7 / mo | Unlimited | 15-min delay |
| Stocks Advanced | $199 / mo | Unlimited | Real-time |
| Stocks Business | $399 / mo | Unlimited | Real-time |

**For FinAlly**: the free tier (5 calls/min → one call every 12 s) is sufficient if we poll at a 15 s interval. Users who want real-time data need the Advanced plan ($199/mo).

---

## Key Endpoints

### 1. Full Market Snapshot — multiple tickers

Fetches the latest snapshot for a comma-separated list of tickers in a single request. This is the primary endpoint for FinAlly's price polling loop.

```
GET /v2/snapshot/locale/us/markets/stocks/tickers
```

**Query parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tickers` | string | No | Comma-separated ticker list, e.g. `AAPL,GOOGL,MSFT`. Empty string returns all tickers. |
| `include_otc` | boolean | No | Include OTC securities. Default: `false`. |
| `apiKey` | string | No | Alternative to Authorization header. |

**Example request**

```python
from massive import RESTClient

client = RESTClient(api_key="YOUR_KEY")

# Returns a list of TickerSnapshot objects
snapshots = client.get_snapshot_all(
    "stocks",
    tickers=["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]
)

for s in snapshots:
    print(s.ticker, s.day.c, s.todays_change_perc)
```

**Raw HTTP example**

```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,GOOGL&apiKey=YOUR_KEY
```

**Response shape**

```json
{
  "count": 2,
  "status": "OK",
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": 0.98,
      "todaysChangePerc": 0.82,
      "updated": 1605195918306274000,
      "day": {
        "o": 119.62,
        "h": 120.53,
        "l": 118.81,
        "c": 120.42,
        "v": 28727868,
        "vw": 119.725
      },
      "lastTrade": {
        "p": 120.47,
        "s": 236,
        "t": 1605195918306274000
      },
      "lastQuote": {
        "P": 120.47,
        "p": 120.46,
        "t": 1605195918507251700
      },
      "prevDay": {
        "o": 118.64,
        "h": 119.68,
        "l": 117.87,
        "c": 119.49,
        "v": 42283200,
        "vw": 119.03
      },
      "min": {
        "o": 120.435,
        "h": 120.468,
        "l": 120.37,
        "c": 120.42
      }
    }
  ]
}
```

**Key fields**

| Field | Description |
|-------|-------------|
| `ticker` | Ticker symbol |
| `day.c` | Current day's closing/latest price |
| `todaysChangePerc` | % change from open |
| `lastTrade.p` | Price of the most recent trade |
| `prevDay.c` | Previous day's closing price (for daily % calc) |
| `updated` | Nanosecond Unix timestamp of last update |

---

### 2. Single Ticker Snapshot

```
GET /v2/snapshot/locale/us/markets/stocks/tickers/{stocksTicker}
```

**Path parameter**: `stocksTicker` — case-sensitive ticker (e.g., `AAPL`).

**Example request**

```python
snapshot = client.get_snapshot_ticker("stocks", "AAPL")
print(snapshot.ticker, snapshot.day.c, snapshot.todays_change_perc)
```

**Response shape** (same structure as above, under `ticker` key instead of `tickers` array):

```json
{
  "status": "OK",
  "request_id": "657e430f1ae768891f018e08e03598d8",
  "ticker": {
    "ticker": "AAPL",
    "todaysChange": 0.98,
    "todaysChangePerc": 0.82,
    "day": { "o": 119.62, "h": 120.53, "l": 118.81, "c": 120.42, "v": 28727868 },
    "lastTrade": { "p": 120.47, "s": 236 },
    "prevDay": { "c": 119.49 }
  }
}
```

---

### 3. Unified Snapshot (v3) — multi-asset

The v3 endpoint supports filtering by ticker list or range, up to 250 tickers per call, across asset classes.

```
GET /v3/snapshot
```

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `ticker.any_of` | string | Comma-separated tickers, max 250 |
| `type` | string | Asset class: `stocks`, `options`, `forex`, `crypto` |
| `limit` | integer | Results per page, default 10, max 250 |
| `order` | string | `asc` or `desc` |
| `sort` | string | Field to sort by |

**Example request**

```python
# Using the Python client (v3 snapshot)
result = client.list_snapshot_chain(
    "stocks",
    params={"ticker.any_of": "AAPL,GOOGL,MSFT,TSLA,NVDA"}
)
for item in result:
    print(item.ticker, item.session.close)
```

**Response shape**

```json
{
  "status": "OK",
  "request_id": "abc123",
  "results": [
    {
      "ticker": "AAPL",
      "type": "stocks",
      "market_status": "open",
      "session": {
        "open": 119.62,
        "high": 120.53,
        "low": 118.81,
        "close": 120.42,
        "volume": 28727868,
        "change": 0.93,
        "change_percent": 0.78
      },
      "last_trade": {
        "price": 120.47,
        "size": 236,
        "timestamp": "2023-10-01T14:32:18Z"
      },
      "fmv": 120.45
    }
  ],
  "next_url": "https://api.massive.com/v3/snapshot?cursor=abc"
}
```

**Note on real-time vs delayed**: `fmv` (Fair Market Value) is a real-time composite price available on Advanced/Business plans. On lower tiers, `session.close` reflects 15-minute-delayed data.

---

### 4. Previous Day Bar (End-of-Day)

```
GET /v2/aggs/ticker/{stocksTicker}/prev
```

Use this to seed open prices at startup for daily change calculations.

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `adjusted` | boolean | Split-adjust prices. Default: `true`. |

**Example request**

```python
agg = client.get_previous_close_agg("AAPL")
print(agg[0].c)  # previous day close
```

**Response shape**

```json
{
  "status": "OK",
  "ticker": "AAPL",
  "resultsCount": 1,
  "results": [
    {
      "T": "AAPL",
      "o": 115.55,
      "h": 117.59,
      "l": 114.13,
      "c": 115.97,
      "v": 131704427,
      "vw": 116.31,
      "t": 1605042000000
    }
  ]
}
```

---

## Polling Strategy for FinAlly

Since FinAlly needs prices for the entire watchlist in one shot:

1. **Single call**: use the Full Market Snapshot endpoint with a comma-separated ticker list
2. **Free tier (5 req/min)**: poll every **15 seconds** — conservative, stays within limits
3. **Paid tiers**: poll every **2–5 seconds** for near-real-time feel

```python
import asyncio
from massive import RESTClient

client = RESTClient(api_key=MASSIVE_API_KEY)

async def poll_prices(tickers: list[str], interval: float = 15.0):
    while True:
        snapshots = client.get_snapshot_all("stocks", tickers=tickers)
        for s in snapshots:
            yield s.ticker, s.day.c, s.todays_change_perc
        await asyncio.sleep(interval)
```

---

## Error Handling

The API returns `status: "NOT_FOUND"` for unknown tickers within a multi-ticker response (the rest of the batch still succeeds). Always filter the response:

```python
valid = [s for s in snapshots if s.ticker and s.day is not None]
```

HTTP-level errors:

| Status | Meaning |
|--------|---------|
| 200 | OK — check `status` field in body |
| 403 | Invalid or missing API key |
| 429 | Rate limit exceeded |
| 503 | Service temporarily unavailable |

---

## Installation Summary

```bash
# Add to backend/pyproject.toml dependencies
uv add massive
```

```python
import os
from massive import RESTClient

client = RESTClient(api_key=os.environ["MASSIVE_API_KEY"])
```
