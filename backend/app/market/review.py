"""Market data review — snapshot analysis of current prices in the cache."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .cache import PriceCache
from .models import PriceUpdate


@dataclass(frozen=True, slots=True)
class TickerReview:
    """Summary of a single ticker's current market state."""

    ticker: str
    current_price: float
    previous_price: float
    change: float
    change_percent: float
    direction: str  # "up" | "down" | "flat"
    timestamp: float

    @classmethod
    def from_price_update(cls, update: PriceUpdate) -> TickerReview:
        return cls(
            ticker=update.ticker,
            current_price=update.price,
            previous_price=update.previous_price,
            change=update.change,
            change_percent=update.change_percent,
            direction=update.direction,
            timestamp=update.timestamp,
        )

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "current_price": self.current_price,
            "previous_price": self.previous_price,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
            "timestamp": self.timestamp,
        }


@dataclass
class MarketReview:
    """Aggregate market review derived from a PriceCache snapshot."""

    tickers: list[TickerReview]
    top_gainers: list[TickerReview]
    top_losers: list[TickerReview]
    most_volatile: list[TickerReview]
    market_sentiment: str  # "bullish" | "bearish" | "neutral"
    gainers_count: int
    losers_count: int
    flat_count: int
    average_change_percent: float
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "tickers": [t.to_dict() for t in self.tickers],
            "top_gainers": [t.to_dict() for t in self.top_gainers],
            "top_losers": [t.to_dict() for t in self.top_losers],
            "most_volatile": [t.to_dict() for t in self.most_volatile],
            "market_sentiment": self.market_sentiment,
            "gainers_count": self.gainers_count,
            "losers_count": self.losers_count,
            "flat_count": self.flat_count,
            "average_change_percent": self.average_change_percent,
            "generated_at": self.generated_at,
        }


def _compute_sentiment(gainers: int, losers: int, total: int) -> str:
    """Derive market-wide sentiment from gainer/loser ratio.

    Thresholds: >60% up → bullish, <40% up → bearish, else neutral.
    Returns 'neutral' when total == 0 (no data).
    """
    if total == 0:
        return "neutral"
    gainer_ratio = gainers / total
    if gainer_ratio > 0.60:
        return "bullish"
    if gainer_ratio < 0.40:
        return "bearish"
    return "neutral"


def generate_market_review(cache: PriceCache, top_n: int = 3) -> MarketReview:
    """Analyze the current PriceCache snapshot and return a MarketReview.

    Args:
        cache: The live price cache to snapshot.
        top_n: How many entries to include in gainers/losers/volatile lists.

    Returns:
        A MarketReview with per-ticker stats and aggregate market insights.
    """
    all_updates = cache.get_all()

    ticker_reviews = [
        TickerReview.from_price_update(update) for update in all_updates.values()
    ]

    gainers = [t for t in ticker_reviews if t.direction == "up"]
    losers = [t for t in ticker_reviews if t.direction == "down"]
    flat = [t for t in ticker_reviews if t.direction == "flat"]

    top_gainers = sorted(gainers, key=lambda t: t.change_percent, reverse=True)[:top_n]
    top_losers = sorted(losers, key=lambda t: t.change_percent)[:top_n]
    most_volatile = sorted(ticker_reviews, key=lambda t: abs(t.change_percent), reverse=True)[
        :top_n
    ]

    if ticker_reviews:
        avg_change_pct = round(
            sum(t.change_percent for t in ticker_reviews) / len(ticker_reviews), 4
        )
    else:
        avg_change_pct = 0.0

    sentiment = _compute_sentiment(len(gainers), len(losers), len(ticker_reviews))

    return MarketReview(
        tickers=sorted(ticker_reviews, key=lambda t: t.ticker),
        top_gainers=top_gainers,
        top_losers=top_losers,
        most_volatile=most_volatile,
        market_sentiment=sentiment,
        gainers_count=len(gainers),
        losers_count=len(losers),
        flat_count=len(flat),
        average_change_percent=avg_change_pct,
    )
