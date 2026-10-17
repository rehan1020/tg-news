"""Scoring engine and item routing (breaking vs digest vs discard)."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from src.bot.logger import get_logger
from src.pipeline.clustering import StoryCluster
from src.state.manager import BotState

logger = get_logger(__name__)

CRITICAL_BREAKING_THRESHOLD = 0.90


@dataclass
class ScoreBreakdown:
    """Detailed score factors for auditability and dry-run output."""

    trust: float
    recency: float
    cluster_boost: float
    watchlist_boost: float
    breaking_boost: float
    penalties: float
    total: float


@dataclass
class ScoredCluster:
    """A story cluster with calculated score and assigned route."""

    cluster: StoryCluster
    score: ScoreBreakdown
    route: str  # breaking | digest | discard
    demoted_reason: str | None = None


class ScoringEngine:
    """Calculates multidimensional relevance scores and routes items."""

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).resolve().parent.parent.parent / "config" / "scoring.yml"

        with open(config_path, encoding="utf-8") as f:
            self._cfg: dict[str, Any] = yaml.safe_load(f)

        self._trust_weights: dict[str, float] = self._cfg.get(
            "trust_weights",
            {"official": 1.0, "major": 0.8, "specialist": 0.6, "aggregator": 0.4},
        )
        self._decay_hours: float = float(self._cfg.get("recency", {}).get("decay_hours", 6.0))
        self._cluster_cfg: dict[str, float] = self._cfg.get(
            "cluster", {"log_boost_per_source": 0.15, "max_boost": 0.5}
        )
        self._watchlist_boost: float = float(self._cfg.get("watchlist", {}).get("hit_boost", 0.3))
        self._breaking_boost: float = float(self._cfg.get("breaking_keyword_boost", 0.4))
        self._breaking_keywords: dict[str, list[str]] = self._cfg.get("breaking_keywords", {})
        self._penalty_patterns: list[tuple[re.Pattern, float]] = [
            (re.compile(p["pattern"]), float(p["penalty"]))
            for p in self._cfg.get("penalty_patterns", [])
        ]
        self._thresholds: dict[str, float] = self._cfg.get(
            "thresholds", {"breaking": 0.75, "digest": 0.35}
        )
        self._breaking_cap: int = int(self._cfg.get("per_run_caps", {}).get("breaking_max", 8))

    def calculate_score(
        self,
        cluster: StoryCluster,
        watchlist: list[str],
        now: float | None = None,
    ) -> ScoreBreakdown:
        """Compute the breakdown score for a story cluster."""
        if now is None:
            now = time.time()

        item = cluster.primary_item

        # 1. Trust weight (0.0 to 1.0)
        trust = self._trust_weights.get(item.trust_tier.lower(), 0.5)

        # 2. Recency score (linear decay to 0 over decay_hours)
        age_hours = max(0.0, (now - item.published_at) / 3600.0)
        recency = max(0.0, 1.0 - (age_hours / self._decay_hours))

        # 3. Cluster boost (logarithmic on number of independent sources)
        cluster_size = cluster.size
        log_boost = self._cluster_cfg.get("log_boost_per_source", 0.15)
        max_boost = self._cluster_cfg.get("max_boost", 0.5)
        c_boost = min(max_boost, math.log(cluster_size) * log_boost) if cluster_size > 1 else 0.0

        # 4. Watchlist hit boost
        combined_text = f"{item.title} {item.summary_raw}".lower()
        watchlist_hit = False
        for kw in watchlist:
            kw_clean = kw.strip().lower()
            if kw_clean and re.search(rf"\b{re.escape(kw_clean)}\b", combined_text):
                watchlist_hit = True
                break
        w_boost = self._watchlist_boost if watchlist_hit else 0.0

        # 5. Breaking keywords boost
        sector_kws = self._breaking_keywords.get(item.sector.lower(), [])
        breaking_hit = False
        for kw in sector_kws:
            if kw and re.search(rf"\b{re.escape(kw.lower())}\b", combined_text):
                breaking_hit = True
                break
        b_boost = self._breaking_boost if breaking_hit else 0.0

        # 6. Penalty patterns
        penalties = 0.0
        for pattern, pen_val in self._penalty_patterns:
            if pattern.search(item.title):
                penalties += pen_val

        # Weighted total formula
        # Base: 35% trust + 25% recency + additive boosts - penalties
        total = (trust * 0.35) + (recency * 0.25) + c_boost + w_boost + b_boost - penalties
        total = round(max(0.0, total), 3)

        return ScoreBreakdown(
            trust=round(trust, 2),
            recency=round(recency, 2),
            cluster_boost=round(c_boost, 2),
            watchlist_boost=round(w_boost, 2),
            breaking_boost=round(b_boost, 2),
            penalties=round(penalties, 2),
            total=total,
        )

    def route_clusters(
        self,
        clusters: list[StoryCluster],
        state: BotState,
        quiet_hours: tuple[str, str] | None = None,
        tz_name: str = "UTC",
    ) -> tuple[list[ScoredCluster], list[ScoredCluster], list[ScoredCluster]]:
        """Score and route story clusters into breaking, digest, and discarded buckets."""
        active_watchlist = state.watchlist
        is_quiet = self._is_quiet_hours(quiet_hours, tz_name)

        breaking_candidates: list[ScoredCluster] = []
        digest_items: list[ScoredCluster] = []
        discarded_items: list[ScoredCluster] = []

        tb = self._thresholds.get("breaking", 0.75)
        td = self._thresholds.get("digest", 0.35)

        for cluster in clusters:
            sector = cluster.primary_item.sector.lower()

            # Sector muted check
            if sector in state.muted_sectors:
                score = self.calculate_score(cluster, active_watchlist)
                discarded_items.append(
                    ScoredCluster(cluster, score, route="discard", demoted_reason="sector_muted")
                )
                continue

            score = self.calculate_score(cluster, active_watchlist)

            if score.total >= tb:
                # Check quiet hours hold
                if is_quiet and score.total < CRITICAL_BREAKING_THRESHOLD:
                    digest_items.append(
                        ScoredCluster(
                            cluster,
                            score,
                            route="digest",
                            demoted_reason="quiet_hours_hold",
                        )
                    )
                else:
                    breaking_candidates.append(ScoredCluster(cluster, score, route="breaking"))
            elif score.total >= td:
                digest_items.append(ScoredCluster(cluster, score, route="digest"))
            else:
                discarded_items.append(
                    ScoredCluster(cluster, score, route="discard", demoted_reason="below_threshold")
                )

        # Sort breaking candidates by score descending
        breaking_candidates.sort(key=lambda x: x.score.total, reverse=True)

        # Apply per-run breaking cap (excess demoted to digest)
        breaking_final: list[ScoredCluster] = []
        for idx, item in enumerate(breaking_candidates):
            if idx < self._breaking_cap:
                breaking_final.append(item)
            else:
                item.route = "digest"
                item.demoted_reason = "breaking_cap_overflow"
                digest_items.append(item)

        # Sort digest items by score descending
        digest_items.sort(key=lambda x: x.score.total, reverse=True)

        logger.info(
            "routing completed",
            extra={
                "breaking_count": len(breaking_final),
                "digest_count": len(digest_items),
                "discarded_count": len(discarded_items),
                "quiet_hours_active": is_quiet,
            },
        )
        return breaking_final, digest_items, discarded_items

    @staticmethod
    def _is_quiet_hours(quiet_hours: tuple[str, str] | None, tz_name: str) -> bool:
        """Check if current time in tz_name falls within quiet_hours window (HH:MM-HH:MM)."""
        if not quiet_hours:
            return False

        try:
            tz = ZoneInfo(tz_name)
            now_dt = datetime.now(tz)
            now_mins = now_dt.hour * 60 + now_dt.minute

            start_h, start_m = map(int, quiet_hours[0].split(":"))
            end_h, end_m = map(int, quiet_hours[1].split(":"))
            start_mins = start_h * 60 + start_m
            end_mins = end_h * 60 + end_m

            if start_mins <= end_mins:
                return start_mins <= now_mins < end_mins
            # Wraps around midnight (e.g. 23:00 to 06:00)
            return now_mins >= start_mins or now_mins < end_mins
        except Exception:
            return False
