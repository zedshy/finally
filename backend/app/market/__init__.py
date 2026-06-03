"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate         - Immutable price snapshot dataclass
    PriceCache          - Thread-safe in-memory price store
    MarketDataSource    - Abstract interface for data providers
    create_market_data_source - Factory that selects simulator or Massive
    create_stream_router - FastAPI router factory for SSE endpoint
    TickerReview        - Per-ticker snapshot from a market review
    MarketReview        - Aggregate review of all tickers in the cache
    generate_market_review - Analyze PriceCache and return a MarketReview
"""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .review import MarketReview, TickerReview, generate_market_review
from .stream import create_stream_router

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
    "TickerReview",
    "MarketReview",
    "generate_market_review",
]
