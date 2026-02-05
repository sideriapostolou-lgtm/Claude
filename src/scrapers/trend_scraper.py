"""TikTok trend and viral content scraper."""

import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import httpx
from rich.console import Console

console = Console()


@dataclass
class TrendingSound:
    """Represents a trending sound on TikTok."""
    id: str
    name: str
    author: str
    video_count: int
    growth_rate: float  # percentage
    duration: float  # seconds
    url: str = ""


@dataclass
class TrendingHashtag:
    """Represents a trending hashtag."""
    name: str
    view_count: int
    video_count: int
    growth_rate: float
    related_hashtags: list = field(default_factory=list)
    top_products: list = field(default_factory=list)


@dataclass
class ViralVideo:
    """Represents a viral TikTok video."""
    id: str
    description: str
    views: int
    likes: int
    comments: int
    shares: int
    author: str
    hashtags: list = field(default_factory=list)
    products_mentioned: list = field(default_factory=list)
    sound_id: Optional[str] = None
    posted_at: Optional[datetime] = None
    url: str = ""

    @property
    def engagement_rate(self) -> float:
        """Calculate engagement rate."""
        if self.views == 0:
            return 0
        return ((self.likes + self.comments + self.shares) / self.views) * 100


class TrendScraper:
    """Scraper for TikTok trends and viral content."""

    # Product-related hashtags to monitor
    PRODUCT_HASHTAGS = [
        "tiktokmademebuyit",
        "tiktokshop",
        "tiktokfinds",
        "amazonfinds",
        "viralproducts",
        "musthave2024",
        "homeorganization",
        "beautytok",
        "cleantok",
        "cookingtiktok",
        "fitnesstok",
        "techtok",
        "booktokrecommendations",
        "fashiontiktok",
        "skincareRoutine",
    ]

    def __init__(self, delay: float = 2.0):
        """Initialize the trend scraper."""
        self.delay = delay
        self.session = None

    async def __aenter__(self):
        """Async context manager entry."""
        self.session = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.aclose()

    async def get_trending_sounds(self, limit: int = 20) -> list[TrendingSound]:
        """
        Get currently trending sounds on TikTok.

        These sounds are crucial for viral content creation.
        """
        console.print("[cyan]🎵 Fetching trending sounds...[/cyan]")

        # In production, this would fetch from TikTok's API or scrape
        # For now, returning structure that can be filled
        trending_sounds = [
            TrendingSound(
                id="sound_1",
                name="Original Sound - Trending",
                author="creator",
                video_count=500000,
                growth_rate=125.5,
                duration=15.0,
            ),
        ]

        await asyncio.sleep(self.delay)
        return trending_sounds[:limit]

    async def get_trending_hashtags(
        self,
        category: Optional[str] = None,
        limit: int = 30
    ) -> list[TrendingHashtag]:
        """
        Get trending hashtags, optionally filtered by category.

        Monitors hashtags for:
        - View growth rate
        - Product mentions
        - Engagement patterns
        """
        console.print("[cyan]#️⃣ Fetching trending hashtags...[/cyan]")

        hashtags = []

        # Filter product-related hashtags if category specified
        target_hashtags = self.PRODUCT_HASHTAGS
        if category:
            # Map categories to relevant hashtags
            category_map = {
                "beauty": ["beautytok", "skincareRoutine", "makeuptutorial"],
                "home": ["homeorganization", "cleantok", "homedecor"],
                "tech": ["techtok", "gadgets", "techreview"],
                "fashion": ["fashiontiktok", "ootd", "styleinspo"],
                "fitness": ["fitnesstok", "workout", "gymtok"],
            }
            target_hashtags = category_map.get(category.lower(), self.PRODUCT_HASHTAGS)

        for tag in target_hashtags[:limit]:
            hashtag_data = await self._fetch_hashtag_data(tag)
            if hashtag_data:
                hashtags.append(hashtag_data)

        return hashtags

    async def _fetch_hashtag_data(self, hashtag: str) -> Optional[TrendingHashtag]:
        """Fetch data for a specific hashtag."""
        await asyncio.sleep(self.delay / 2)

        # Return placeholder data structure
        return TrendingHashtag(
            name=f"#{hashtag}",
            view_count=0,
            video_count=0,
            growth_rate=0,
            related_hashtags=[],
            top_products=[],
        )

    async def get_viral_videos(
        self,
        hashtag: Optional[str] = None,
        min_views: int = 100000,
        days: int = 7,
        limit: int = 50
    ) -> list[ViralVideo]:
        """
        Get viral videos from the past N days.

        Focuses on product-related content for UGC inspiration.
        """
        console.print(f"[cyan]🎬 Fetching viral videos (last {days} days)...[/cyan]")

        videos = []

        if hashtag:
            videos = await self._fetch_videos_by_hashtag(hashtag, min_views, limit)
        else:
            # Fetch from multiple product hashtags
            for tag in self.PRODUCT_HASHTAGS[:5]:
                tag_videos = await self._fetch_videos_by_hashtag(tag, min_views, limit // 5)
                videos.extend(tag_videos)

        # Sort by engagement rate
        videos.sort(key=lambda v: v.engagement_rate, reverse=True)
        return videos[:limit]

    async def _fetch_videos_by_hashtag(
        self,
        hashtag: str,
        min_views: int,
        limit: int
    ) -> list[ViralVideo]:
        """Fetch viral videos for a specific hashtag."""
        await asyncio.sleep(self.delay)
        return []

    async def analyze_content_patterns(self, videos: list[ViralVideo]) -> dict:
        """
        Analyze patterns in viral videos to inform UGC creation.

        Returns insights on:
        - Optimal video length
        - Hook patterns
        - Call-to-action effectiveness
        - Best posting times
        """
        if not videos:
            return {}

        # Calculate averages
        total_views = sum(v.views for v in videos)
        total_likes = sum(v.likes for v in videos)
        avg_engagement = sum(v.engagement_rate for v in videos) / len(videos)

        # Analyze hashtag frequency
        hashtag_counts = {}
        for video in videos:
            for tag in video.hashtags:
                hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1

        top_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "sample_size": len(videos),
            "total_views": total_views,
            "total_likes": total_likes,
            "avg_engagement_rate": round(avg_engagement, 2),
            "top_hashtags": [tag for tag, _ in top_hashtags],
            "content_insights": {
                "optimal_length": "15-30 seconds",
                "hook_timing": "First 3 seconds critical",
                "cta_placement": "End of video + caption",
                "text_overlay": "Use throughout for accessibility",
            },
            "viral_patterns": [
                "Problem → Solution format",
                "Before/After transformation",
                "Unboxing with genuine reaction",
                "Day in my life integration",
                "Trend participation with product",
            ],
        }

    async def find_emerging_trends(self, lookback_hours: int = 24) -> list[dict]:
        """
        Find emerging trends before they go fully viral.

        This is the key to finding 'upcoming winners'.
        """
        console.print(f"[cyan]📈 Finding emerging trends (last {lookback_hours}h)...[/cyan]")

        emerging = []

        # Analyze rapid growth patterns
        trending_hashtags = await self.get_trending_hashtags(limit=50)

        for hashtag in trending_hashtags:
            if hashtag.growth_rate > 50:  # 50%+ growth
                emerging.append({
                    "type": "hashtag",
                    "name": hashtag.name,
                    "growth_rate": hashtag.growth_rate,
                    "current_views": hashtag.view_count,
                    "potential": "high" if hashtag.growth_rate > 100 else "medium",
                    "recommendation": "Create content now for early mover advantage",
                })

        return emerging


class ProductTrendAnalyzer:
    """Analyzes trends specifically for product opportunities."""

    def __init__(self):
        """Initialize the analyzer."""
        self.trend_scraper = TrendScraper()

    async def find_product_opportunities(self) -> list[dict]:
        """
        Find product opportunities based on trend analysis.

        Combines multiple signals:
        - Hashtag trends
        - Sound trends
        - Viral video analysis
        - Search volume patterns
        """
        opportunities = []

        async with self.trend_scraper:
            # Get trending data
            hashtags = await self.trend_scraper.get_trending_hashtags()
            sounds = await self.trend_scraper.get_trending_sounds()
            emerging = await self.trend_scraper.find_emerging_trends()

            # Analyze for product opportunities
            for trend in emerging:
                opportunity = {
                    "trend": trend,
                    "product_categories": self._map_trend_to_categories(trend),
                    "urgency": self._calculate_urgency(trend),
                    "competition_level": "low" if trend.get("growth_rate", 0) > 100 else "medium",
                    "recommended_action": self._get_recommendation(trend),
                }
                opportunities.append(opportunity)

        return opportunities

    def _map_trend_to_categories(self, trend: dict) -> list[str]:
        """Map a trend to potential product categories."""
        name = trend.get("name", "").lower()

        category_keywords = {
            "beauty": ["beauty", "skincare", "makeup", "glow"],
            "home": ["home", "clean", "organize", "decor"],
            "tech": ["tech", "gadget", "phone", "electronic"],
            "fashion": ["fashion", "style", "outfit", "wear"],
            "fitness": ["fitness", "gym", "workout", "health"],
            "kitchen": ["kitchen", "cook", "recipe", "food"],
        }

        categories = []
        for category, keywords in category_keywords.items():
            if any(kw in name for kw in keywords):
                categories.append(category)

        return categories if categories else ["general"]

    def _calculate_urgency(self, trend: dict) -> str:
        """Calculate urgency to act on a trend."""
        growth = trend.get("growth_rate", 0)
        if growth > 150:
            return "🔴 Act immediately"
        elif growth > 100:
            return "🟠 Act within 24h"
        elif growth > 50:
            return "🟡 Act within 48h"
        return "🟢 Monitor"

    def _get_recommendation(self, trend: dict) -> str:
        """Get actionable recommendation for a trend."""
        growth = trend.get("growth_rate", 0)
        if growth > 100:
            return "Create UGC content immediately. High viral potential."
        elif growth > 50:
            return "Research products in this category. Prepare content."
        return "Add to watchlist. Continue monitoring."
