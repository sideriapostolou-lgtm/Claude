"""Hashtag analysis and monitoring for TikTok trends."""

import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class HashtagMetrics:
    """Metrics for a tracked hashtag."""
    name: str
    views: int
    videos: int
    timestamp: datetime = field(default_factory=datetime.now)
    growth_24h: float = 0.0
    growth_7d: float = 0.0
    avg_engagement: float = 0.0
    top_creators: list = field(default_factory=list)
    related_products: list = field(default_factory=list)


class HashtagScraper:
    """
    Monitors and analyzes hashtags for product opportunities.

    Key features:
    - Track hashtag growth over time
    - Identify product-related hashtags
    - Find emerging viral hashtags
    - Analyze hashtag combinations for maximum reach
    """

    # Winning hashtag combinations for TikTok Shop
    WINNING_COMBINATIONS = [
        ["tiktokmademebuyit", "amazonfinds", "musthave"],
        ["tiktokshop", "viralproduct", "trending"],
        ["unboxing", "haul", "shopwithme"],
        ["review", "honest", "worthit"],
        ["lifehack", "gamechanger", "didyouknow"],
    ]

    def __init__(self, data_dir: str = "./data"):
        """Initialize the hashtag scraper."""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.data_dir / "hashtag_history.json"
        self.history: dict = self._load_history()

    def _load_history(self) -> dict:
        """Load hashtag history from file."""
        try:
            with open(self.history_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"hashtags": {}, "snapshots": []}

    def _save_history(self):
        """Save hashtag history to file."""
        with open(self.history_file, "w") as f:
            json.dump(self.history, f, indent=2, default=str)

    async def track_hashtag(self, hashtag: str) -> HashtagMetrics:
        """
        Track a specific hashtag and get current metrics.
        """
        hashtag = hashtag.lstrip("#").lower()
        console.print(f"[dim]Tracking #{hashtag}...[/dim]")

        # Fetch current metrics (in production, would hit actual APIs)
        metrics = HashtagMetrics(
            name=hashtag,
            views=0,
            videos=0,
        )

        # Store in history
        if hashtag not in self.history["hashtags"]:
            self.history["hashtags"][hashtag] = []

        self.history["hashtags"][hashtag].append({
            "views": metrics.views,
            "videos": metrics.videos,
            "timestamp": datetime.now().isoformat(),
        })

        # Calculate growth if we have history
        if len(self.history["hashtags"][hashtag]) > 1:
            metrics.growth_24h = self._calculate_growth(hashtag, hours=24)
            metrics.growth_7d = self._calculate_growth(hashtag, hours=168)

        self._save_history()
        return metrics

    def _calculate_growth(self, hashtag: str, hours: int) -> float:
        """Calculate growth rate over specified hours."""
        data = self.history["hashtags"].get(hashtag, [])
        if len(data) < 2:
            return 0.0

        cutoff = datetime.now() - timedelta(hours=hours)

        # Find data points
        current = data[-1]
        old_data = [d for d in data if datetime.fromisoformat(d["timestamp"]) <= cutoff]

        if not old_data:
            return 0.0

        old = old_data[-1]

        if old["views"] == 0:
            return 0.0

        return ((current["views"] - old["views"]) / old["views"]) * 100

    async def find_trending_product_hashtags(
        self,
        category: Optional[str] = None,
        min_growth: float = 20.0
    ) -> list[HashtagMetrics]:
        """
        Find hashtags that are trending and product-related.

        Returns hashtags with:
        - High growth rate
        - Product purchase intent
        - Good engagement
        """
        console.print("[cyan]🔍 Finding trending product hashtags...[/cyan]")

        product_hashtags = [
            "tiktokmademebuyit",
            "tiktokshop",
            "amazonfinds",
            "viralproducts",
            "musthave",
            "shopwithme",
            "haul",
            "unboxing",
            "worthit",
            "gamechanger",
            "bestpurchase",
            "shoppinghaul",
            "newfinds",
            "dailyfinds",
            "budgetfinds",
        ]

        # Add category-specific hashtags
        if category:
            category_tags = {
                "beauty": ["beautytok", "skincarehaul", "makeupfinds", "beautymusthaves"],
                "home": ["hometok", "homeorganization", "homefinds", "cleaningtiktok"],
                "tech": ["techtok", "gadgetfinds", "techhaul", "techreview"],
                "fashion": ["fashionfinds", "stylehaul", "ootdinspo", "clothinghaul"],
                "kitchen": ["kitchenfinds", "kitchengadgets", "cookingtiktok", "foodtiktok"],
            }
            product_hashtags.extend(category_tags.get(category.lower(), []))

        trending = []
        for tag in product_hashtags:
            metrics = await self.track_hashtag(tag)
            if metrics.growth_24h >= min_growth or metrics.growth_7d >= min_growth:
                trending.append(metrics)

            await asyncio.sleep(0.5)  # Rate limiting

        # Sort by growth
        trending.sort(key=lambda x: x.growth_24h, reverse=True)
        return trending

    def get_optimal_hashtag_set(
        self,
        product_category: str,
        target_audience: str = "general"
    ) -> list[str]:
        """
        Generate optimal hashtag set for maximum reach.

        TikTok allows up to 100 characters or ~4-5 hashtags for best performance.
        Mix of:
        - 1-2 high volume hashtags (for reach)
        - 1-2 niche hashtags (for targeting)
        - 1 branded/unique hashtag (for tracking)
        """
        # Base product hashtags (high volume)
        base_tags = ["fyp", "tiktokshop", "tiktokmademebuyit"]

        # Category-specific tags
        category_tags = {
            "beauty": ["beautytok", "skincare", "makeuptutorial"],
            "home": ["hometok", "homeorganization", "homedecor"],
            "tech": ["techtok", "gadgets", "techreview"],
            "fashion": ["fashiontiktok", "ootd", "styleinspo"],
            "kitchen": ["kitchentok", "cookinghacks", "foodie"],
            "fitness": ["fitnesstok", "workout", "gymlife"],
            "pet": ["pettok", "dogsoftiktok", "catsoftiktok"],
        }

        # Audience-specific tags
        audience_tags = {
            "general": ["viral", "trending"],
            "budget": ["budgetfinds", "affordable"],
            "luxury": ["luxuryfinds", "treatyourself"],
            "mom": ["momtok", "momlife"],
            "student": ["collegetiktok", "studentlife"],
        }

        # Combine optimal set
        optimal = []

        # Add 1 broad reach tag
        optimal.append(base_tags[0])

        # Add 2 product-related tags
        optimal.extend(base_tags[1:3])

        # Add 1-2 category tags
        cat_tags = category_tags.get(product_category.lower(), ["trending"])
        optimal.extend(cat_tags[:2])

        # Add 1 audience tag
        aud_tags = audience_tags.get(target_audience.lower(), ["viral"])
        optimal.append(aud_tags[0])

        # Limit to 5-6 hashtags for optimal performance
        return optimal[:6]

    def display_hashtag_report(self, hashtags: list[HashtagMetrics]):
        """Display a formatted hashtag report."""
        table = Table(title="📊 Trending Product Hashtags")

        table.add_column("Hashtag", style="cyan")
        table.add_column("Views", justify="right")
        table.add_column("24h Growth", justify="right")
        table.add_column("7d Growth", justify="right")
        table.add_column("Status", justify="center")

        for h in hashtags[:15]:
            growth_24h = f"{h.growth_24h:+.1f}%" if h.growth_24h else "N/A"
            growth_7d = f"{h.growth_7d:+.1f}%" if h.growth_7d else "N/A"

            if h.growth_24h > 50:
                status = "🔥 Hot"
            elif h.growth_24h > 20:
                status = "📈 Rising"
            elif h.growth_24h > 0:
                status = "→ Stable"
            else:
                status = "📉 Declining"

            table.add_row(
                f"#{h.name}",
                f"{h.views:,}",
                growth_24h,
                growth_7d,
                status,
            )

        console.print(table)


class HashtagCombinationOptimizer:
    """Optimizes hashtag combinations for maximum viral potential."""

    def __init__(self):
        """Initialize the optimizer."""
        self.tested_combinations: dict = {}

    def generate_combinations(
        self,
        product_name: str,
        category: str,
        features: list[str]
    ) -> list[list[str]]:
        """
        Generate multiple hashtag combinations to test.

        Returns 3-5 different combinations for A/B testing.
        """
        combinations = []

        # Combination 1: Maximum reach
        combinations.append([
            "fyp",
            "foryou",
            "viral",
            "tiktokshop",
            "musthave",
        ])

        # Combination 2: Product-focused
        combinations.append([
            "tiktokmademebuyit",
            "shopwithme",
            f"{category}tok",
            "worthit",
            "newfinds",
        ])

        # Combination 3: Problem-solution
        combinations.append([
            "gamechanger",
            "lifehack",
            "didyouknow",
            "tiktokshop",
            category,
        ])

        # Combination 4: Niche targeting
        niche_tags = [f"{category}finds", f"{category}musthaves"]
        combinations.append([
            *niche_tags,
            "smallbusiness",
            "supportsmall",
            "qualityproducts",
        ])

        return combinations

    def score_combination(self, hashtags: list[str], metrics: dict) -> float:
        """
        Score a hashtag combination based on performance metrics.

        Factors:
        - Total reach potential
        - Competition level
        - Relevance to product
        - Historical performance
        """
        score = 0.0

        for tag in hashtags:
            tag_metrics = metrics.get(tag, {})
            # Reach potential (views)
            score += min(tag_metrics.get("views", 0) / 1_000_000, 10)
            # Growth bonus
            score += tag_metrics.get("growth_rate", 0) * 0.1
            # Lower competition bonus
            if tag_metrics.get("videos", 0) < 100000:
                score += 2

        return score
