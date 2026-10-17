"""Story clustering — groups multi-source coverage of the same event."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.feeds.models import FeedItem
from src.pipeline.simhash import is_near_duplicate


@dataclass
class StoryCluster:
    """A cluster of items from different sources covering the same event."""

    primary_item: FeedItem
    items: list[FeedItem] = field(default_factory=list)

    @property
    def sources(self) -> set[str]:
        return {item.source_id for item in self.items}

    @property
    def size(self) -> int:
        return len(self.sources)


def cluster_items(
    items: list[FeedItem],
    max_simhash_distance: int = 14,
) -> list[StoryCluster]:
    """Group items covering the same story across different sources into clusters."""
    clusters: list[StoryCluster] = []

    # Trust tier ranking for choosing primary item
    trust_rank = {
        "official": 4,
        "major": 3,
        "specialist": 2,
        "aggregator": 1,
    }

    for item in items:
        matched_cluster: StoryCluster | None = None
        for cluster in clusters:
            # Check near-duplicate title with primary or any member
            if (
                item.simhash
                and cluster.primary_item.simhash
                and is_near_duplicate(
                    item.simhash, cluster.primary_item.simhash, max_distance=max_simhash_distance
                )
            ):
                matched_cluster = cluster
                break

        if matched_cluster:
            matched_cluster.items.append(item)
            # If new item has higher trust tier, elevate it to primary
            if trust_rank.get(item.trust_tier, 0) > trust_rank.get(
                matched_cluster.primary_item.trust_tier, 0
            ):
                matched_cluster.primary_item = item
        else:
            clusters.append(StoryCluster(primary_item=item, items=[item]))

    return clusters
