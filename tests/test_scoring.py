"""Unit tests for scoring engine, clustering, and routing."""

from __future__ import annotations

import time

from src.feeds.models import FeedItem
from src.pipeline.clustering import StoryCluster, cluster_items
from src.pipeline.scoring import ScoringEngine
from src.pipeline.simhash import compute_simhash
from src.state.manager import BotState


def _make_item(
    title: str,
    sector: str = "world",
    trust_tier: str = "major",
    published_at: float | None = None,
    source_id: str = "src1",
) -> FeedItem:
    if published_at is None:
        published_at = time.time()
    return FeedItem(
        id=f"hash_{title[:10]}",
        title=title,
        url=f"https://example.com/{title[:10]}",
        canonical_url=f"https://example.com/{title[:10]}",
        source_id=source_id,
        source_name="Test Source",
        sector=sector,
        trust_tier=trust_tier,
        published_at=published_at,
        simhash=compute_simhash(title),
    )


class TestScoringEngine:
    def test_trust_tier_weights(self):
        engine = ScoringEngine()
        now = time.time()

        item_off = _make_item("Headline", trust_tier="official", published_at=now)
        item_maj = _make_item("Headline", trust_tier="major", published_at=now)
        item_spe = _make_item("Headline", trust_tier="specialist", published_at=now)
        item_agg = _make_item("Headline", trust_tier="aggregator", published_at=now)

        s_off = engine.calculate_score(StoryCluster(item_off, [item_off]), [], now)
        s_maj = engine.calculate_score(StoryCluster(item_maj, [item_maj]), [], now)
        s_spe = engine.calculate_score(StoryCluster(item_spe, [item_spe]), [], now)
        s_agg = engine.calculate_score(StoryCluster(item_agg, [item_agg]), [], now)

        assert s_off.trust > s_maj.trust > s_spe.trust > s_agg.trust
        assert s_off.total > s_maj.total > s_spe.total > s_agg.total

    def test_recency_decay(self):
        engine = ScoringEngine()
        now = time.time()

        fresh = _make_item("Headline", published_at=now)
        mid_age = _make_item("Headline", published_at=now - (3 * 3600))  # 3 hrs ago
        expired = _make_item("Headline", published_at=now - (7 * 3600))  # 7 hrs ago

        s_fresh = engine.calculate_score(StoryCluster(fresh, [fresh]), [], now)
        s_mid = engine.calculate_score(StoryCluster(mid_age, [mid_age]), [], now)
        s_exp = engine.calculate_score(StoryCluster(expired, [expired]), [], now)

        assert s_fresh.recency == 1.0
        assert 0.45 <= s_mid.recency <= 0.55
        assert s_exp.recency == 0.0

    def test_cluster_size_boost(self):
        engine = ScoringEngine()
        now = time.time()

        i1 = _make_item("Headline Story", source_id="src1", published_at=now)
        i2 = _make_item("Headline Story", source_id="src2", published_at=now)
        i3 = _make_item("Headline Story", source_id="src3", published_at=now)

        single = StoryCluster(i1, [i1])
        multi = StoryCluster(i1, [i1, i2, i3])

        s_single = engine.calculate_score(single, [], now)
        s_multi = engine.calculate_score(multi, [], now)

        assert s_single.cluster_boost == 0.0
        assert s_multi.cluster_boost > 0.0
        assert s_multi.total > s_single.total

    def test_watchlist_hit_boost(self):
        engine = ScoringEngine()
        now = time.time()

        item = _make_item("Apple AAPL reports record quarterly revenue", published_at=now)
        cluster = StoryCluster(item, [item])

        s_no_watch = engine.calculate_score(cluster, ["TSLA", "BTC"], now)
        s_hit = engine.calculate_score(cluster, ["AAPL", "BTC"], now)

        assert s_no_watch.watchlist_boost == 0.0
        assert s_hit.watchlist_boost == 0.3
        assert s_hit.total > s_no_watch.total

    def test_breaking_keywords_boost(self):
        engine = ScoringEngine()
        now = time.time()

        routine = _make_item(
            "Central bank meeting concludes today", sector="business", published_at=now
        )
        breaking = _make_item(
            "Central bank announces surprise rate cut", sector="business", published_at=now
        )

        s_routine = engine.calculate_score(StoryCluster(routine, [routine]), [], now)
        s_breaking = engine.calculate_score(StoryCluster(breaking, [breaking]), [], now)

        assert s_routine.breaking_boost == 0.0
        assert s_breaking.breaking_boost == 0.4
        assert s_breaking.total > s_routine.total

    def test_penalty_patterns(self):
        engine = ScoringEngine()
        now = time.time()

        news = _make_item("Tech Giant launches new AI model", published_at=now)
        opinion = _make_item("Opinion: Why Tech Giant AI model might fail", published_at=now)
        listicle = _make_item("5 ways Tech Giant model changes search", published_at=now)

        s_news = engine.calculate_score(StoryCluster(news, [news]), [], now)
        s_op = engine.calculate_score(StoryCluster(opinion, [opinion]), [], now)
        s_list = engine.calculate_score(StoryCluster(listicle, [listicle]), [], now)

        assert s_news.penalties == 0.0
        assert s_op.penalties >= 0.3
        assert s_list.penalties >= 0.2
        assert s_op.total < s_news.total

    def test_overflow_demotion_to_digest(self):
        engine = ScoringEngine()
        now = time.time()
        state = BotState()

        # Create 12 high-scoring breaking items (breaking cap is 8)
        clusters = []
        for i in range(12):
            item = _make_item(
                f"Emergency rate cut default sanctions crisis {i}",
                sector="business",
                trust_tier="official",
                published_at=now,
                source_id=f"src_{i}",
            )
            clusters.append(StoryCluster(item, [item]))

        breaking, digest, discarded = engine.route_clusters(clusters, state)

        # Only top 8 should remain in breaking
        assert len(breaking) == 8
        # Remaining 4 overflow demoted to digest
        demoted = [d for d in digest if d.demoted_reason == "breaking_cap_overflow"]
        assert len(demoted) == 4

    def test_sector_mute_routing(self):
        engine = ScoringEngine()
        state = BotState(muted_sectors=["crypto"])

        item_crypto = _make_item("Major crypto exchange exploit hack", sector="crypto")
        cluster = StoryCluster(item_crypto, [item_crypto])

        breaking, digest, discarded = engine.route_clusters([cluster], state)
        assert len(breaking) == 0
        assert len(discarded) == 1
        assert discarded[0].demoted_reason == "sector_muted"

    def test_quiet_hours_holds_non_critical_breaking(self):
        engine = ScoringEngine()
        state = BotState()

        # Regular breaking item (specialist tier, score ~ 0.86, below 0.90 critical)
        non_critical = _make_item(
            "Central bank announces rate hike",
            sector="business",
            trust_tier="specialist",
            published_at=time.time(),
        )
        # Critical breaking item (official tier, score 1.0, >= 0.90 critical)
        critical = _make_item(
            "Central bank announces rate hike",
            sector="business",
            trust_tier="official",
            published_at=time.time(),
        )

        cluster_non_crit = StoryCluster(non_critical, [non_critical])
        cluster_crit = StoryCluster(critical, [critical])

        breaking, digest, discarded = engine.route_clusters(
            [cluster_non_crit, cluster_crit],
            state,
            quiet_hours=("00:00", "23:59"),
            tz_name="UTC",
        )

        # Critical breaks through
        assert len(breaking) == 1
        assert breaking[0].cluster.primary_item.trust_tier == "official"

        # Non-critical held for digest
        held = [d for d in digest if d.demoted_reason == "quiet_hours_hold"]
        assert len(held) == 1
        assert held[0].cluster.primary_item.trust_tier == "specialist"

    def test_clustering_groups_near_duplicate_stories(self):
        now = time.time()
        i1 = _make_item(
            "European Central Bank raises interest rates by 50 basis points",
            trust_tier="major",
            source_id="bbc",
            published_at=now,
        )
        i2 = _make_item(
            "European Central Bank raises interest rate by 50 basis points in Frankfurt",
            trust_tier="official",
            source_id="ecb",
            published_at=now,
        )
        i3 = _make_item(
            "Bitcoin reaches record high after exchange-traded fund approval",
            trust_tier="specialist",
            source_id="coindesk",
            published_at=now,
        )

        clusters = cluster_items([i1, i2, i3])
        assert len(clusters) == 2

        # First cluster has 2 items from bbc and ecb
        ecb_cluster = next(c for c in clusters if c.size == 2)
        assert ecb_cluster.sources == {"bbc", "ecb"}
        # Official tier should be elevated to primary
        assert ecb_cluster.primary_item.trust_tier == "official"
