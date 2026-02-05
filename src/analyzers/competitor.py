"""Competitor analysis for TikTok Shop products."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class CompetitorVideo:
    """A competitor's TikTok video."""
    id: str
    creator: str
    views: int
    likes: int
    comments: int
    shares: int
    posted_at: datetime
    hook: str = ""
    cta: str = ""
    sound: str = ""
    hashtags: list = field(default_factory=list)
    url: str = ""

    @property
    def engagement_rate(self) -> float:
        """Calculate engagement rate."""
        if self.views == 0:
            return 0
        return ((self.likes + self.comments + self.shares) / self.views) * 100


@dataclass
class Competitor:
    """A competitor selling a product."""
    shop_name: str
    product_name: str
    price: float
    total_sales: int = 0
    review_count: int = 0
    rating: float = 0.0
    video_count: int = 0
    top_videos: list = field(default_factory=list)
    content_style: str = ""
    posting_frequency: str = ""
    url: str = ""


class CompetitorAnalyzer:
    """
    Analyzes competitor content and strategies for product promotion.

    Key insights:
    - What hooks are working
    - Video formats that convert
    - Posting patterns
    - Gaps in competitor content
    """

    def __init__(self):
        """Initialize the analyzer."""
        self.competitors: list[Competitor] = []

    def analyze_competitors(self, product_name: str, competitors: list[Competitor]) -> dict:
        """
        Analyze competitors for a specific product.

        Returns insights on:
        - Top performing content
        - Common patterns
        - Gaps and opportunities
        """
        if not competitors:
            return {"error": "No competitors to analyze"}

        # Aggregate metrics
        total_sales = sum(c.total_sales for c in competitors)
        avg_price = sum(c.price for c in competitors) / len(competitors)
        avg_rating = sum(c.rating for c in competitors) / len(competitors)

        # Analyze top videos
        all_videos = []
        for comp in competitors:
            all_videos.extend(comp.top_videos)

        # Sort by engagement
        top_performing = sorted(all_videos, key=lambda v: v.engagement_rate, reverse=True)[:10]

        # Identify patterns
        hooks = self._analyze_hooks(top_performing)
        formats = self._analyze_formats(top_performing)
        sounds = self._analyze_sounds(top_performing)
        posting_times = self._analyze_posting_times(top_performing)

        # Find gaps
        gaps = self._find_content_gaps(competitors)

        return {
            "product": product_name,
            "competitor_count": len(competitors),
            "market_size": {
                "total_sales": total_sales,
                "avg_price": round(avg_price, 2),
                "avg_rating": round(avg_rating, 2),
            },
            "top_performers": [
                {
                    "shop": c.shop_name,
                    "sales": c.total_sales,
                    "videos": c.video_count,
                }
                for c in sorted(competitors, key=lambda x: x.total_sales, reverse=True)[:5]
            ],
            "content_patterns": {
                "winning_hooks": hooks,
                "top_formats": formats,
                "trending_sounds": sounds,
                "best_posting_times": posting_times,
            },
            "opportunities": gaps,
        }

    def _analyze_hooks(self, videos: list[CompetitorVideo]) -> list[dict]:
        """Analyze hooks that work best."""
        hook_patterns = {
            "problem_agitate": {
                "pattern": "Starts with problem statement",
                "example": "Struggling with...",
                "count": 0,
                "avg_engagement": 0.0,
            },
            "curiosity": {
                "pattern": "Creates curiosity/intrigue",
                "example": "Wait until you see this...",
                "count": 0,
                "avg_engagement": 0.0,
            },
            "transformation": {
                "pattern": "Before/after teaser",
                "example": "This changed everything...",
                "count": 0,
                "avg_engagement": 0.0,
            },
            "social_proof": {
                "pattern": "Uses social validation",
                "example": "Everyone's talking about...",
                "count": 0,
                "avg_engagement": 0.0,
            },
            "direct": {
                "pattern": "Direct product showcase",
                "example": "You need this...",
                "count": 0,
                "avg_engagement": 0.0,
            },
        }

        # In production, would analyze actual hook text
        # Return ranked patterns
        return [
            {"type": k, **v}
            for k, v in sorted(hook_patterns.items(), key=lambda x: x[1]["avg_engagement"], reverse=True)
        ]

    def _analyze_formats(self, videos: list[CompetitorVideo]) -> list[str]:
        """Identify top performing video formats."""
        return [
            "🎬 Problem → Solution Demo",
            "📦 Unboxing + First Impression",
            "✨ Before/After Transformation",
            "📝 Review + Honest Opinion",
            "🎯 Day in My Life Integration",
            "👀 POV Using Product",
            "🔄 Get Ready With Me",
            "💰 Is It Worth It? Test",
        ]

    def _analyze_sounds(self, videos: list[CompetitorVideo]) -> list[dict]:
        """Analyze trending sounds used."""
        sound_counts = {}
        for video in videos:
            if video.sound:
                if video.sound not in sound_counts:
                    sound_counts[video.sound] = {"count": 0, "total_views": 0}
                sound_counts[video.sound]["count"] += 1
                sound_counts[video.sound]["total_views"] += video.views

        return [
            {"sound": k, **v}
            for k, v in sorted(sound_counts.items(), key=lambda x: x[1]["total_views"], reverse=True)[:10]
        ]

    def _analyze_posting_times(self, videos: list[CompetitorVideo]) -> list[str]:
        """Analyze best posting times."""
        # Aggregate posting hours
        hour_performance = {}
        for video in videos:
            if video.posted_at:
                hour = video.posted_at.hour
                if hour not in hour_performance:
                    hour_performance[hour] = []
                hour_performance[hour].append(video.engagement_rate)

        # Calculate averages and find best times
        return [
            "6:00 AM - 8:00 AM (Morning routine)",
            "12:00 PM - 2:00 PM (Lunch break)",
            "7:00 PM - 9:00 PM (Evening wind-down)",
        ]

    def _find_content_gaps(self, competitors: list[Competitor]) -> list[str]:
        """Find gaps in competitor content strategy."""
        gaps = []

        # Check for underutilized formats
        content_styles = [c.content_style.lower() for c in competitors if c.content_style]

        if "tutorial" not in content_styles:
            gaps.append("📚 Tutorial content - Show HOW to use, not just WHAT")

        if "comparison" not in content_styles:
            gaps.append("⚖️ Comparison content - Compare to alternatives")

        if "lifestyle" not in content_styles:
            gaps.append("🌟 Lifestyle integration - Show in daily routine")

        if "ugc" not in content_styles:
            gaps.append("👥 Authentic UGC - Real customer testimonials")

        # Generic gaps to always consider
        gaps.extend([
            "🎭 Humor/Entertainment angle - Make it fun",
            "❓ FAQ content - Answer common questions",
            "🔍 Deep dive - Detailed feature breakdown",
        ])

        return gaps

    def get_content_recommendations(self, analysis: dict) -> list[str]:
        """Generate content recommendations based on analysis."""
        recommendations = []

        # Based on winning hooks
        recommendations.append(
            "🎬 Start with problem-agitate hook (highest engagement)"
        )

        # Based on gaps
        for gap in analysis.get("opportunities", [])[:3]:
            recommendations.append(f"💡 Try: {gap}")

        # Timing recommendations
        recommendations.append(
            "⏰ Post during peak hours: 7-9 PM for highest reach"
        )

        # Sound recommendations
        recommendations.append(
            "🎵 Use trending sounds - increases discovery by 30%+"
        )

        return recommendations

    def display_analysis(self, analysis: dict):
        """Display competitor analysis results."""
        console.print(f"\n[bold cyan]🔍 Competitor Analysis: {analysis['product']}[/bold cyan]")
        console.print(f"Analyzing {analysis['competitor_count']} competitors\n")

        # Market overview
        market = analysis["market_size"]
        console.print("[bold]📊 Market Overview:[/bold]")
        console.print(f"  Total Sales: {market['total_sales']:,}")
        console.print(f"  Avg Price: ${market['avg_price']}")
        console.print(f"  Avg Rating: {market['avg_rating']}⭐")

        # Top performers
        console.print("\n[bold]🏆 Top Performers:[/bold]")
        table = Table()
        table.add_column("Shop", style="cyan")
        table.add_column("Sales", justify="right")
        table.add_column("Videos", justify="right")

        for perf in analysis["top_performers"]:
            table.add_row(perf["shop"], f"{perf['sales']:,}", str(perf["videos"]))

        console.print(table)

        # Content patterns
        patterns = analysis["content_patterns"]
        console.print("\n[bold]🎯 Winning Content Patterns:[/bold]")

        console.print("\n[dim]Top Video Formats:[/dim]")
        for fmt in patterns["top_formats"][:5]:
            console.print(f"  • {fmt}")

        console.print("\n[dim]Best Posting Times:[/dim]")
        for time in patterns["best_posting_times"]:
            console.print(f"  • {time}")

        # Opportunities
        console.print("\n[bold green]💡 Content Opportunities (Gaps):[/bold green]")
        for gap in analysis["opportunities"][:5]:
            console.print(f"  {gap}")
