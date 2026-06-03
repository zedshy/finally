"""Tests for the market data review module."""

import time

from app.market.cache import PriceCache
from app.market.review import (
    MarketReview,
    TickerReview,
    _compute_sentiment,
    generate_market_review,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _populated_cache(*ticker_price_pairs: tuple[str, float, float]) -> PriceCache:
    """Build a PriceCache with explicit (ticker, prev_price, current_price) pairs."""
    cache = PriceCache()
    for ticker, prev, current in ticker_price_pairs:
        cache.update(ticker, prev)   # First update sets previous_price == price (flat)
        cache.update(ticker, current)  # Second update registers the actual move
    return cache


# ---------------------------------------------------------------------------
# TickerReview tests
# ---------------------------------------------------------------------------

class TestTickerReview:
    def test_from_price_update_up(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 191.00)
        review = TickerReview.from_price_update(update)

        assert review.ticker == "AAPL"
        assert review.current_price == 191.00
        assert review.previous_price == 190.00
        assert review.direction == "up"
        assert review.change == 1.00
        assert review.change_percent > 0

    def test_from_price_update_down(self):
        cache = PriceCache()
        cache.update("TSLA", 250.00)
        update = cache.update("TSLA", 245.00)
        review = TickerReview.from_price_update(update)

        assert review.direction == "down"
        assert review.change == -5.00
        assert review.change_percent < 0

    def test_from_price_update_flat(self):
        cache = PriceCache()
        update = cache.update("MSFT", 420.00)  # First update → flat
        review = TickerReview.from_price_update(update)

        assert review.direction == "flat"
        assert review.change == 0.0
        assert review.change_percent == 0.0

    def test_to_dict_keys(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.00)
        review = TickerReview.from_price_update(update)
        d = review.to_dict()

        expected_keys = {
            "ticker", "current_price", "previous_price",
            "change", "change_percent", "direction", "timestamp",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self):
        cache = PriceCache()
        cache.update("GOOGL", 175.00)
        update = cache.update("GOOGL", 180.00)
        review = TickerReview.from_price_update(update)
        d = review.to_dict()

        assert d["ticker"] == "GOOGL"
        assert d["current_price"] == 180.00
        assert d["direction"] == "up"

    def test_is_frozen(self):
        """TickerReview is a frozen dataclass — mutations raise AttributeError."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.00)
        review = TickerReview.from_price_update(update)
        try:
            review.ticker = "NOPE"  # type: ignore[misc]
            assert False, "Should have raised"
        except (AttributeError, TypeError):
            pass


# ---------------------------------------------------------------------------
# _compute_sentiment tests
# ---------------------------------------------------------------------------

class TestComputeSentiment:
    def test_bullish_when_majority_up(self):
        # 7 gainers, 3 losers out of 10 → 70% → bullish
        assert _compute_sentiment(7, 3, 10) == "bullish"

    def test_bearish_when_majority_down(self):
        # 3 gainers, 7 losers out of 10 → 30% → bearish
        assert _compute_sentiment(3, 7, 10) == "bearish"

    def test_neutral_mixed(self):
        # 5 gainers, 5 losers → 50% → neutral
        assert _compute_sentiment(5, 5, 10) == "neutral"

    def test_neutral_exactly_at_bullish_threshold(self):
        # Exactly 60% is NOT bullish (must be > 0.60)
        assert _compute_sentiment(6, 4, 10) == "neutral"

    def test_bullish_just_above_threshold(self):
        # 7/10 = 70% is bullish
        assert _compute_sentiment(7, 0, 10) == "bullish"

    def test_neutral_on_empty_cache(self):
        assert _compute_sentiment(0, 0, 0) == "neutral"

    def test_all_gainers_bullish(self):
        assert _compute_sentiment(10, 0, 10) == "bullish"

    def test_all_losers_bearish(self):
        assert _compute_sentiment(0, 10, 10) == "bearish"


# ---------------------------------------------------------------------------
# generate_market_review tests
# ---------------------------------------------------------------------------

class TestGenerateMarketReview:
    def test_empty_cache_returns_empty_review(self):
        cache = PriceCache()
        review = generate_market_review(cache)

        assert isinstance(review, MarketReview)
        assert review.tickers == []
        assert review.top_gainers == []
        assert review.top_losers == []
        assert review.most_volatile == []
        assert review.market_sentiment == "neutral"
        assert review.gainers_count == 0
        assert review.losers_count == 0
        assert review.flat_count == 0
        assert review.average_change_percent == 0.0

    def test_single_ticker_flat(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)  # flat (first update)
        review = generate_market_review(cache)

        assert len(review.tickers) == 1
        assert review.flat_count == 1
        assert review.gainers_count == 0
        assert review.losers_count == 0

    def test_gainer_counted_correctly(self):
        cache = _populated_cache(("AAPL", 190.00, 195.00))
        review = generate_market_review(cache)

        assert review.gainers_count == 1
        assert review.losers_count == 0
        assert len(review.top_gainers) == 1
        assert review.top_gainers[0].ticker == "AAPL"

    def test_loser_counted_correctly(self):
        cache = _populated_cache(("TSLA", 250.00, 240.00))
        review = generate_market_review(cache)

        assert review.losers_count == 1
        assert review.gainers_count == 0
        assert len(review.top_losers) == 1
        assert review.top_losers[0].ticker == "TSLA"

    def test_top_gainers_sorted_descending(self):
        cache = _populated_cache(
            ("AAPL", 100.00, 102.00),   # +2%
            ("GOOGL", 100.00, 105.00),  # +5%
            ("MSFT", 100.00, 103.00),   # +3%
        )
        review = generate_market_review(cache, top_n=3)

        # Should be sorted: GOOGL (+5%), MSFT (+3%), AAPL (+2%)
        assert review.top_gainers[0].ticker == "GOOGL"
        assert review.top_gainers[1].ticker == "MSFT"
        assert review.top_gainers[2].ticker == "AAPL"

    def test_top_losers_sorted_ascending(self):
        cache = _populated_cache(
            ("AAPL", 100.00, 98.00),    # -2%
            ("GOOGL", 100.00, 93.00),   # -7%
            ("MSFT", 100.00, 96.00),    # -4%
        )
        review = generate_market_review(cache, top_n=3)

        # Sorted by change_percent ascending: GOOGL (-7%), MSFT (-4%), AAPL (-2%)
        assert review.top_losers[0].ticker == "GOOGL"
        assert review.top_losers[1].ticker == "MSFT"
        assert review.top_losers[2].ticker == "AAPL"

    def test_most_volatile_sorted_by_abs_change(self):
        cache = _populated_cache(
            ("AAPL", 100.00, 102.00),   # +2%
            ("TSLA", 100.00, 90.00),    # -10%  ← most volatile
            ("MSFT", 100.00, 104.00),   # +4%
        )
        review = generate_market_review(cache, top_n=3)

        assert review.most_volatile[0].ticker == "TSLA"

    def test_top_n_limits_lists(self):
        cache = _populated_cache(
            ("A", 100.00, 101.00),
            ("B", 100.00, 103.00),
            ("C", 100.00, 105.00),
            ("D", 100.00, 102.00),
        )
        review = generate_market_review(cache, top_n=2)

        assert len(review.top_gainers) == 2
        assert len(review.most_volatile) == 2

    def test_top_n_1(self):
        cache = _populated_cache(
            ("AAPL", 100.00, 105.00),
            ("TSLA", 100.00, 95.00),
        )
        review = generate_market_review(cache, top_n=1)

        assert len(review.top_gainers) == 1
        assert len(review.top_losers) == 1

    def test_tickers_sorted_alphabetically(self):
        cache = _populated_cache(
            ("TSLA", 250.00, 255.00),
            ("AAPL", 190.00, 192.00),
            ("MSFT", 420.00, 418.00),
        )
        review = generate_market_review(cache)

        tickers = [t.ticker for t in review.tickers]
        assert tickers == sorted(tickers)

    def test_average_change_percent(self):
        # AAPL: +10%, TSLA: -10% → average = 0%
        cache = _populated_cache(
            ("AAPL", 100.00, 110.00),
            ("TSLA", 100.00, 90.00),
        )
        review = generate_market_review(cache)
        assert review.average_change_percent == 0.0

    def test_average_change_percent_all_positive(self):
        cache = _populated_cache(
            ("AAPL", 100.00, 102.00),   # +2%
            ("MSFT", 100.00, 104.00),   # +4%
        )
        review = generate_market_review(cache)
        assert review.average_change_percent == 3.0

    def test_sentiment_bullish(self):
        # 8 gainers, 2 losers (80% up)
        cache = PriceCache()
        tickers = ["A", "B", "C", "D", "E", "F", "G", "H"]
        for t in tickers:
            cache.update(t, 100.00)
            cache.update(t, 102.00)
        cache.update("X", 100.00)
        cache.update("X", 98.00)
        cache.update("Y", 100.00)
        cache.update("Y", 99.00)
        review = generate_market_review(cache)
        assert review.market_sentiment == "bullish"

    def test_sentiment_bearish(self):
        # Mostly losers
        cache = PriceCache()
        for t in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            cache.update(t, 100.00)
            cache.update(t, 95.00)
        cache.update("X", 100.00)
        cache.update("X", 102.00)
        cache.update("Y", 100.00)
        cache.update("Y", 103.00)
        review = generate_market_review(cache)
        assert review.market_sentiment == "bearish"

    def test_sentiment_neutral(self):
        cache = _populated_cache(
            ("AAPL", 100.00, 102.00),
            ("TSLA", 100.00, 98.00),
        )
        review = generate_market_review(cache)
        assert review.market_sentiment == "neutral"

    def test_generated_at_is_recent(self):
        cache = PriceCache()
        before = time.time()
        review = generate_market_review(cache)
        after = time.time()
        assert before <= review.generated_at <= after

    def test_to_dict_structure(self):
        cache = _populated_cache(("AAPL", 190.00, 192.00))
        review = generate_market_review(cache)
        d = review.to_dict()

        expected_keys = {
            "tickers", "top_gainers", "top_losers", "most_volatile",
            "market_sentiment", "gainers_count", "losers_count",
            "flat_count", "average_change_percent", "generated_at",
        }
        assert set(d.keys()) == expected_keys
        assert isinstance(d["tickers"], list)
        assert isinstance(d["top_gainers"], list)
        assert isinstance(d["market_sentiment"], str)

    def test_to_dict_tickers_are_dicts(self):
        cache = _populated_cache(("AAPL", 190.00, 192.00))
        review = generate_market_review(cache)
        d = review.to_dict()

        assert len(d["tickers"]) == 1
        ticker_dict = d["tickers"][0]
        assert ticker_dict["ticker"] == "AAPL"
        assert "current_price" in ticker_dict

    def test_all_tickers_appear_in_review(self):
        tickers_expected = {"AAPL", "GOOGL", "MSFT", "TSLA"}
        cache = PriceCache()
        for t in tickers_expected:
            cache.update(t, 100.00)
        review = generate_market_review(cache)
        assert {t.ticker for t in review.tickers} == tickers_expected

    def test_flat_ticker_not_in_gainers_or_losers(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)  # flat
        review = generate_market_review(cache)

        assert review.flat_count == 1
        assert review.gainers_count == 0
        assert review.losers_count == 0
        assert review.top_gainers == []
        assert review.top_losers == []

    def test_mixed_gainers_losers_flat(self):
        cache = PriceCache()
        # AAPL: flat
        cache.update("AAPL", 190.00)
        # MSFT: up
        cache.update("MSFT", 420.00)
        cache.update("MSFT", 425.00)
        # TSLA: down
        cache.update("TSLA", 250.00)
        cache.update("TSLA", 245.00)

        review = generate_market_review(cache)
        assert review.gainers_count == 1
        assert review.losers_count == 1
        assert review.flat_count == 1
        assert len(review.tickers) == 3
