"""
Winning Product Analyzer for TikTok Shop.

This module identifies products with high viral and sales potential
based on multiple data signals and proven winning criteria.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


class ProductPotential(Enum):
    """Product potential classification."""
    WINNER = "🏆 Winner"
    HIGH_POTENTIAL = "⭐ High Potential"
    RISING = "📈 Rising"
    WATCH = "👀 Watch"
    SKIP = "⏭️ Skip"


@dataclass
class WinningScore:
    """Detailed scoring breakdown for a product."""
    total_score: int
    potential: ProductPotential

    # Individual scores (0-100 each)
    virality_score: int = 0
    profit_score: int = 0
    demand_score: int = 0
    competition_score: int = 0
    content_score: int = 0
    timing_score: int = 0

    # Detailed breakdown
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
    opportunities: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)


@dataclass
class ProductCandidate:
    """A product candidate for analysis."""
    id: str
    name: str
    price: float
    cost: Optional[float] = None
    category: str = ""

    # Sales metrics
    daily_sales: int = 0
    total_sales: int = 0
    sales_trend: str = "stable"  # rising, stable, declining

    # Social metrics
    video_count: int = 0
    total_views: int = 0
    avg_engagement: float = 0.0
    hashtag_mentions: int = 0

    # Review metrics
    review_count: int = 0
    avg_rating: float = 0.0

    # Competition
    seller_count: int = 0
    top_seller_sales: int = 0

    # Timing
    trend_start_date: Optional[datetime] = None
    peak_season: Optional[str] = None

    url: str = ""
    images: list = field(default_factory=list)


class WinningProductAnalyzer:
    """
    Analyzes products to identify winners with high viral and sales potential.

    The Winning Product Score (WPS) is calculated based on:

    1. VIRALITY SCORE (0-100): How likely to go viral on TikTok
       - Video engagement rates
       - Hashtag trend momentum
       - Content creation ease
       - Visual appeal

    2. PROFIT SCORE (0-100): Profit margin and pricing optimization
       - Markup potential (aim for 3x+)
       - Sweet spot pricing ($15-35)
       - Shipping cost efficiency
       - Return rate estimation

    3. DEMAND SCORE (0-100): Market demand signals
       - Sales velocity
       - Search trends
       - Seasonal factors
       - Problem-solving value

    4. COMPETITION SCORE (0-100): Market competition analysis
       - Number of sellers
       - Market saturation
       - Entry barriers
       - Differentiation potential

    5. CONTENT SCORE (0-100): UGC creation potential
       - Demonstrability
       - Before/after potential
       - Unboxing appeal
       - Story potential

    6. TIMING SCORE (0-100): Market timing analysis
       - Trend lifecycle stage
       - Seasonal relevance
       - Market saturation trajectory
    """

    # Winning product criteria thresholds
    WINNING_THRESHOLDS = {
        "min_daily_sales": 50,
        "min_profit_margin": 0.5,  # 50%
        "min_rating": 4.0,
        "max_competition": 100,  # sellers
        "optimal_price_min": 15,
        "optimal_price_max": 35,
        "min_video_engagement": 5.0,  # %
    }

    # Category-specific multipliers
    CATEGORY_MULTIPLIERS = {
        "beauty": 1.2,
        "gadgets": 1.15,
        "home": 1.1,
        "fashion": 1.0,
        "fitness": 1.1,
        "pet": 1.05,
        "kitchen": 1.1,
    }

    def __init__(self):
        """Initialize the analyzer."""
        self.analyzed_products: list = []

    def analyze_product(self, product: ProductCandidate) -> WinningScore:
        """
        Perform comprehensive analysis on a product candidate.

        Returns a WinningScore with detailed breakdown and recommendations.
        """
        # Calculate individual scores
        virality = self._calculate_virality_score(product)
        profit = self._calculate_profit_score(product)
        demand = self._calculate_demand_score(product)
        competition = self._calculate_competition_score(product)
        content = self._calculate_content_score(product)
        timing = self._calculate_timing_score(product)

        # Weight the scores
        weights = {
            "virality": 0.20,
            "profit": 0.20,
            "demand": 0.20,
            "competition": 0.15,
            "content": 0.15,
            "timing": 0.10,
        }

        total = int(
            virality * weights["virality"] +
            profit * weights["profit"] +
            demand * weights["demand"] +
            competition * weights["competition"] +
            content * weights["content"] +
            timing * weights["timing"]
        )

        # Apply category multiplier
        multiplier = self.CATEGORY_MULTIPLIERS.get(product.category.lower(), 1.0)
        total = min(100, int(total * multiplier))

        # Determine potential
        if total >= 80:
            potential = ProductPotential.WINNER
        elif total >= 65:
            potential = ProductPotential.HIGH_POTENTIAL
        elif total >= 50:
            potential = ProductPotential.RISING
        elif total >= 35:
            potential = ProductPotential.WATCH
        else:
            potential = ProductPotential.SKIP

        # Generate insights
        strengths, weaknesses = self._identify_swot(product, {
            "virality": virality,
            "profit": profit,
            "demand": demand,
            "competition": competition,
            "content": content,
            "timing": timing,
        })

        opportunities = self._identify_opportunities(product)
        recommendations = self._generate_recommendations(product, total)

        return WinningScore(
            total_score=total,
            potential=potential,
            virality_score=virality,
            profit_score=profit,
            demand_score=demand,
            competition_score=competition,
            content_score=content,
            timing_score=timing,
            strengths=strengths,
            weaknesses=weaknesses,
            opportunities=opportunities,
            recommendations=recommendations,
        )

    def _calculate_virality_score(self, product: ProductCandidate) -> int:
        """Calculate virality potential score."""
        score = 0

        # Video engagement (0-30)
        if product.avg_engagement >= 10:
            score += 30
        elif product.avg_engagement >= 5:
            score += 20
        elif product.avg_engagement >= 2:
            score += 10

        # Existing video content (0-25)
        if product.video_count >= 100:
            score += 25
        elif product.video_count >= 50:
            score += 20
        elif product.video_count >= 10:
            score += 15
        elif product.video_count >= 1:
            score += 10

        # Total views (0-25)
        if product.total_views >= 10_000_000:
            score += 25
        elif product.total_views >= 1_000_000:
            score += 20
        elif product.total_views >= 100_000:
            score += 15
        elif product.total_views >= 10_000:
            score += 10

        # Hashtag momentum (0-20)
        if product.hashtag_mentions >= 10000:
            score += 20
        elif product.hashtag_mentions >= 1000:
            score += 15
        elif product.hashtag_mentions >= 100:
            score += 10

        return min(100, score)

    def _calculate_profit_score(self, product: ProductCandidate) -> int:
        """Calculate profit potential score."""
        score = 0

        # Price in sweet spot (0-30)
        if 15 <= product.price <= 35:
            score += 30
        elif 10 <= product.price <= 50:
            score += 20
        elif product.price <= 75:
            score += 10

        # Profit margin if cost known (0-40)
        if product.cost:
            margin = (product.price - product.cost) / product.price
            if margin >= 0.7:  # 70%+
                score += 40
            elif margin >= 0.5:  # 50%+
                score += 30
            elif margin >= 0.3:  # 30%+
                score += 20
            elif margin >= 0.2:  # 20%+
                score += 10
        else:
            # Estimate based on typical margins
            if product.price >= 20:
                score += 25  # Assume decent margin possible

        # Impulse buy potential (0-30)
        if product.price <= 30:
            score += 30
        elif product.price <= 50:
            score += 20
        elif product.price <= 75:
            score += 10

        return min(100, score)

    def _calculate_demand_score(self, product: ProductCandidate) -> int:
        """Calculate market demand score."""
        score = 0

        # Daily sales velocity (0-35)
        if product.daily_sales >= 200:
            score += 35
        elif product.daily_sales >= 100:
            score += 30
        elif product.daily_sales >= 50:
            score += 25
        elif product.daily_sales >= 20:
            score += 15
        elif product.daily_sales >= 5:
            score += 10

        # Sales trend (0-25)
        if product.sales_trend == "rising":
            score += 25
        elif product.sales_trend == "stable":
            score += 15
        else:
            score += 5

        # Review validation (0-25)
        if product.review_count >= 500 and product.avg_rating >= 4.5:
            score += 25
        elif product.review_count >= 100 and product.avg_rating >= 4.0:
            score += 20
        elif product.review_count >= 50 and product.avg_rating >= 4.0:
            score += 15
        elif product.review_count >= 10:
            score += 10

        # Total sales proof (0-15)
        if product.total_sales >= 10000:
            score += 15
        elif product.total_sales >= 1000:
            score += 10
        elif product.total_sales >= 100:
            score += 5

        return min(100, score)

    def _calculate_competition_score(self, product: ProductCandidate) -> int:
        """Calculate competition score (higher = less competition = better)."""
        score = 0

        # Number of sellers (0-40)
        if product.seller_count <= 10:
            score += 40  # Low competition
        elif product.seller_count <= 25:
            score += 30
        elif product.seller_count <= 50:
            score += 20
        elif product.seller_count <= 100:
            score += 10

        # Market concentration (0-30)
        if product.top_seller_sales > 0 and product.total_sales > 0:
            concentration = product.top_seller_sales / product.total_sales
            if concentration <= 0.2:  # Fragmented market
                score += 30
            elif concentration <= 0.4:
                score += 20
            elif concentration <= 0.6:
                score += 10
        else:
            score += 15  # Unknown, assume moderate

        # Entry potential (0-30)
        # Lower price = easier entry
        if product.price <= 25:
            score += 30
        elif product.price <= 50:
            score += 20
        elif product.price <= 100:
            score += 10

        return min(100, score)

    def _calculate_content_score(self, product: ProductCandidate) -> int:
        """Calculate UGC content creation potential."""
        score = 50  # Base score - will be adjusted by category

        # Category-based content potential
        high_content_categories = ["beauty", "gadgets", "kitchen", "fitness", "home"]
        if product.category.lower() in high_content_categories:
            score += 25

        # Has existing successful content (0-25)
        if product.video_count >= 50 and product.avg_engagement >= 5:
            score += 25
        elif product.video_count >= 10:
            score += 15

        return min(100, score)

    def _calculate_timing_score(self, product: ProductCandidate) -> int:
        """Calculate market timing score."""
        score = 50  # Base score

        # Trend lifecycle (0-30)
        if product.trend_start_date:
            days_trending = (datetime.now() - product.trend_start_date).days
            if days_trending <= 14:  # Early stage
                score += 30
            elif days_trending <= 30:  # Growth stage
                score += 25
            elif days_trending <= 60:  # Peak stage
                score += 15
            else:  # Maturity/decline
                score += 5
        else:
            score += 15  # Unknown timing

        # Sales trend momentum (0-20)
        if product.sales_trend == "rising":
            score += 20
        elif product.sales_trend == "stable":
            score += 10

        return min(100, score)

    def _identify_swot(self, product: ProductCandidate, scores: dict) -> tuple:
        """Identify strengths and weaknesses."""
        strengths = []
        weaknesses = []

        if scores["virality"] >= 70:
            strengths.append("High viral potential - proven engagement")
        elif scores["virality"] < 40:
            weaknesses.append("Limited viral history - needs content push")

        if scores["profit"] >= 70:
            strengths.append("Strong profit margins")
        elif scores["profit"] < 40:
            weaknesses.append("Tight margins - watch costs carefully")

        if scores["demand"] >= 70:
            strengths.append("Proven market demand")
        elif scores["demand"] < 40:
            weaknesses.append("Unproven demand - higher risk")

        if scores["competition"] >= 70:
            strengths.append("Low competition - room to dominate")
        elif scores["competition"] < 40:
            weaknesses.append("High competition - differentiation needed")

        if scores["content"] >= 70:
            strengths.append("Excellent content/demo potential")
        elif scores["content"] < 40:
            weaknesses.append("Challenging to create engaging content")

        if scores["timing"] >= 70:
            strengths.append("Perfect timing - early in trend cycle")
        elif scores["timing"] < 40:
            weaknesses.append("Late to trend - saturation risk")

        return strengths, weaknesses

    def _identify_opportunities(self, product: ProductCandidate) -> list:
        """Identify growth opportunities."""
        opportunities = []

        if product.video_count < 50:
            opportunities.append("First-mover advantage in content creation")

        if product.seller_count < 25:
            opportunities.append("Low seller count - establish market position")

        if product.sales_trend == "rising":
            opportunities.append("Riding upward trend momentum")

        if product.price <= 30:
            opportunities.append("Impulse buy price point - high conversion potential")

        if product.avg_rating >= 4.5:
            opportunities.append("High ratings = strong social proof for UGC")

        return opportunities

    def _generate_recommendations(self, product: ProductCandidate, score: int) -> list:
        """Generate actionable recommendations."""
        recommendations = []

        if score >= 80:
            recommendations.extend([
                "🎯 TAKE ACTION: This is a winner - start UGC production immediately",
                "Create 3-5 different video angles to test",
                "Order samples and create authentic review content",
                "Use trending sounds with problem→solution format",
            ])
        elif score >= 65:
            recommendations.extend([
                "📈 HIGH POTENTIAL: Worth pursuing with strategy",
                "Test with 2-3 UGC videos before scaling",
                "Monitor competitor content for differentiation ideas",
                "Consider unique angles competitors aren't using",
            ])
        elif score >= 50:
            recommendations.extend([
                "👀 MONITOR: Shows promise but needs validation",
                "Create one test video to gauge response",
                "Track trend trajectory for 1-2 weeks",
                "Look for unique positioning opportunities",
            ])
        else:
            recommendations.extend([
                "⏭️ CONSIDER SKIPPING: Better opportunities exist",
                "Only pursue if you have unique differentiation",
                "Focus resources on higher-scoring products",
            ])

        return recommendations

    def display_analysis(self, product: ProductCandidate, score: WinningScore):
        """Display formatted analysis results."""
        # Main score panel
        console.print(Panel(
            f"[bold]{product.name}[/bold]\n"
            f"Price: ${product.price:.2f} | Category: {product.category}\n\n"
            f"[bold]Overall Score: {score.total_score}/100[/bold]\n"
            f"Potential: {score.potential.value}",
            title="🎯 Product Analysis",
            border_style="cyan",
        ))

        # Score breakdown table
        table = Table(title="📊 Score Breakdown")
        table.add_column("Metric", style="cyan")
        table.add_column("Score", justify="center")
        table.add_column("Status", justify="center")

        def status_emoji(s):
            if s >= 70: return "🟢"
            elif s >= 50: return "🟡"
            else: return "🔴"

        table.add_row("Virality", f"{score.virality_score}", status_emoji(score.virality_score))
        table.add_row("Profit", f"{score.profit_score}", status_emoji(score.profit_score))
        table.add_row("Demand", f"{score.demand_score}", status_emoji(score.demand_score))
        table.add_row("Competition", f"{score.competition_score}", status_emoji(score.competition_score))
        table.add_row("Content", f"{score.content_score}", status_emoji(score.content_score))
        table.add_row("Timing", f"{score.timing_score}", status_emoji(score.timing_score))

        console.print(table)

        # Strengths and weaknesses
        if score.strengths:
            console.print("\n[green]✅ Strengths:[/green]")
            for s in score.strengths:
                console.print(f"  • {s}")

        if score.weaknesses:
            console.print("\n[yellow]⚠️ Weaknesses:[/yellow]")
            for w in score.weaknesses:
                console.print(f"  • {w}")

        if score.opportunities:
            console.print("\n[blue]💡 Opportunities:[/blue]")
            for o in score.opportunities:
                console.print(f"  • {o}")

        # Recommendations
        console.print("\n[bold]📋 Recommendations:[/bold]")
        for r in score.recommendations:
            console.print(f"  {r}")


class BatchProductAnalyzer:
    """Analyze multiple products and rank them."""

    def __init__(self):
        """Initialize batch analyzer."""
        self.analyzer = WinningProductAnalyzer()

    def analyze_batch(self, products: list[ProductCandidate]) -> list[tuple]:
        """
        Analyze a batch of products and return ranked results.

        Returns list of (product, score) tuples sorted by total score.
        """
        results = []

        for product in products:
            score = self.analyzer.analyze_product(product)
            results.append((product, score))

        # Sort by total score descending
        results.sort(key=lambda x: x[1].total_score, reverse=True)
        return results

    def display_ranking(self, results: list[tuple], top_n: int = 10):
        """Display ranked product results."""
        table = Table(title=f"🏆 Top {top_n} Winning Products")

        table.add_column("Rank", justify="center", style="bold")
        table.add_column("Product", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Score", justify="center")
        table.add_column("Potential", justify="center")

        for i, (product, score) in enumerate(results[:top_n], 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}"

            table.add_row(
                medal,
                product.name[:40] + "..." if len(product.name) > 40 else product.name,
                f"${product.price:.2f}",
                f"{score.total_score}/100",
                score.potential.value,
            )

        console.print(table)
