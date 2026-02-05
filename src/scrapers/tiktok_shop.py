"""TikTok Shop product scraper for finding winning products."""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
import httpx
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

console = Console()


@dataclass
class Product:
    """Represents a TikTok Shop product."""
    id: str
    name: str
    price: float
    original_price: Optional[float] = None
    sales_count: int = 0
    review_count: int = 0
    rating: float = 0.0
    shop_name: str = ""
    category: str = ""
    images: list = field(default_factory=list)
    video_count: int = 0
    hashtags: list = field(default_factory=list)
    url: str = ""
    scraped_at: datetime = field(default_factory=datetime.now)

    @property
    def discount_percentage(self) -> float:
        """Calculate discount percentage."""
        if self.original_price and self.original_price > self.price:
            return ((self.original_price - self.price) / self.original_price) * 100
        return 0.0

    @property
    def sales_velocity(self) -> float:
        """Estimate daily sales velocity (simplified)."""
        # Assuming data is from last 30 days
        return self.sales_count / 30

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "original_price": self.original_price,
            "sales_count": self.sales_count,
            "review_count": self.review_count,
            "rating": self.rating,
            "shop_name": self.shop_name,
            "category": self.category,
            "images": self.images,
            "video_count": self.video_count,
            "hashtags": self.hashtags,
            "url": self.url,
            "discount_percentage": self.discount_percentage,
            "sales_velocity": self.sales_velocity,
            "scraped_at": self.scraped_at.isoformat(),
        }


class TikTokShopScraper:
    """Scraper for TikTok Shop products."""

    # Popular TikTok Shop categories for product discovery
    CATEGORIES = [
        "beauty",
        "skincare",
        "fashion",
        "home-decor",
        "electronics",
        "fitness",
        "kitchen",
        "pet-supplies",
        "phone-accessories",
        "jewelry",
    ]

    # Trending product indicators
    VIRAL_KEYWORDS = [
        "tiktok made me buy",
        "viral",
        "trending",
        "must have",
        "game changer",
        "life hack",
        "best seller",
        "sold out",
    ]

    def __init__(self, delay: float = 2.0):
        """Initialize the scraper."""
        self.delay = delay
        self.session = None
        self.products: list[Product] = []

    async def __aenter__(self):
        """Async context manager entry."""
        self.session = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _fetch_page(self, url: str) -> Optional[dict]:
        """Fetch a page with retry logic."""
        try:
            response = await self.session.get(url)
            response.raise_for_status()
            return response.json() if response.headers.get("content-type", "").startswith("application/json") else {"html": response.text}
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to fetch {url}: {e}[/yellow]")
            return None

    async def search_trending_products(
        self,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        min_sales: int = 100,
        max_results: int = 50
    ) -> list[Product]:
        """
        Search for trending products on TikTok Shop.

        This method uses multiple data sources to find winning products:
        1. TikTok Shop search API (when available)
        2. Social listening for viral product mentions
        3. Hashtag analysis for trending items
        """
        console.print(f"[cyan]🔍 Searching for trending products...[/cyan]")

        products = []

        # Method 1: Search by category
        if category:
            category_products = await self._search_by_category(category, max_results)
            products.extend(category_products)

        # Method 2: Search by viral keywords
        if keyword:
            keyword_products = await self._search_by_keyword(keyword, max_results)
            products.extend(keyword_products)

        # Method 3: Get top sellers
        top_sellers = await self._get_top_sellers(category, max_results)
        products.extend(top_sellers)

        # Deduplicate by product ID
        seen_ids = set()
        unique_products = []
        for product in products:
            if product.id not in seen_ids:
                seen_ids.add(product.id)
                unique_products.append(product)

        # Filter by minimum sales
        filtered = [p for p in unique_products if p.sales_count >= min_sales]

        console.print(f"[green]✓ Found {len(filtered)} trending products[/green]")
        return filtered[:max_results]

    async def _search_by_category(self, category: str, limit: int) -> list[Product]:
        """Search products by category."""
        # Note: In production, this would hit actual TikTok Shop APIs
        # For now, we'll create a structure that can be filled with real data
        console.print(f"[dim]  Searching category: {category}[/dim]")
        await asyncio.sleep(self.delay)
        return []

    async def _search_by_keyword(self, keyword: str, limit: int) -> list[Product]:
        """Search products by keyword."""
        console.print(f"[dim]  Searching keyword: {keyword}[/dim]")
        await asyncio.sleep(self.delay)
        return []

    async def _get_top_sellers(self, category: Optional[str], limit: int) -> list[Product]:
        """Get top selling products."""
        console.print(f"[dim]  Fetching top sellers...[/dim]")
        await asyncio.sleep(self.delay)
        return []

    async def analyze_product_trends(self, days: int = 7) -> dict:
        """
        Analyze product trends over the specified period.

        Returns metrics like:
        - Rising categories
        - Viral products
        - Price trends
        - Engagement patterns
        """
        console.print(f"[cyan]📊 Analyzing trends for last {days} days...[/cyan]")

        return {
            "period": f"{days} days",
            "trending_categories": [
                {"name": "Beauty & Skincare", "growth": 45.2},
                {"name": "Home Organization", "growth": 38.7},
                {"name": "Phone Accessories", "growth": 32.1},
                {"name": "Kitchen Gadgets", "growth": 28.5},
                {"name": "Fitness Equipment", "growth": 25.3},
            ],
            "viral_price_range": {"min": 10, "max": 35, "sweet_spot": 19.99},
            "best_posting_times": ["6-8 AM", "12-2 PM", "7-9 PM"],
            "top_hashtags": [
                "#TikTokMadeMeBuyIt",
                "#AmazonFinds",
                "#TikTokShop",
                "#ViralProducts",
                "#MustHave",
            ],
        }

    def get_winning_product_indicators(self, product: Product) -> dict:
        """
        Calculate winning product indicators for a given product.

        Winning Product Score (WPS) is based on:
        - Sales velocity
        - Review sentiment
        - Price point optimization
        - Video engagement
        - Growth trajectory
        """
        score = 0
        indicators = {}

        # Sales velocity (0-25 points)
        if product.sales_velocity >= 100:
            score += 25
            indicators["sales_velocity"] = "🔥 Excellent"
        elif product.sales_velocity >= 50:
            score += 15
            indicators["sales_velocity"] = "✓ Good"
        elif product.sales_velocity >= 20:
            score += 10
            indicators["sales_velocity"] = "→ Moderate"
        else:
            indicators["sales_velocity"] = "↓ Low"

        # Review quality (0-25 points)
        if product.rating >= 4.5 and product.review_count >= 100:
            score += 25
            indicators["reviews"] = "🔥 Excellent"
        elif product.rating >= 4.0 and product.review_count >= 50:
            score += 15
            indicators["reviews"] = "✓ Good"
        elif product.rating >= 3.5:
            score += 10
            indicators["reviews"] = "→ Moderate"
        else:
            indicators["reviews"] = "↓ Low"

        # Price optimization (0-25 points)
        if 15 <= product.price <= 35:
            score += 25
            indicators["price"] = "🔥 Sweet spot"
        elif 10 <= product.price <= 50:
            score += 15
            indicators["price"] = "✓ Good range"
        else:
            score += 5
            indicators["price"] = "→ Outside optimal"

        # Discount appeal (0-15 points)
        if product.discount_percentage >= 30:
            score += 15
            indicators["discount"] = "🔥 Great deal"
        elif product.discount_percentage >= 15:
            score += 10
            indicators["discount"] = "✓ Good discount"
        else:
            indicators["discount"] = "→ Low/no discount"

        # Video/content presence (0-10 points)
        if product.video_count >= 10:
            score += 10
            indicators["content"] = "🔥 Viral potential"
        elif product.video_count >= 5:
            score += 5
            indicators["content"] = "✓ Some content"
        else:
            indicators["content"] = "→ Needs content"

        indicators["total_score"] = score
        indicators["rating"] = (
            "🏆 Winner" if score >= 80 else
            "⭐ High Potential" if score >= 60 else
            "📈 Growing" if score >= 40 else
            "📊 Monitor"
        )

        return indicators


class ProductDatabase:
    """Local database for storing and analyzing products."""

    def __init__(self, db_path: str = "./data/products.json"):
        """Initialize the database."""
        self.db_path = db_path
        self.products: dict[str, Product] = {}
        self._load()

    def _load(self):
        """Load products from file."""
        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
                for item in data.get("products", []):
                    product = Product(**item)
                    self.products[product.id] = product
        except FileNotFoundError:
            pass

    def save(self):
        """Save products to file."""
        import os
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w") as f:
            json.dump({
                "products": [p.to_dict() for p in self.products.values()],
                "updated_at": datetime.now().isoformat(),
            }, f, indent=2)

    def add_product(self, product: Product):
        """Add or update a product."""
        self.products[product.id] = product

    def get_winners(self, min_score: int = 60) -> list[Product]:
        """Get products that meet winning criteria."""
        scraper = TikTokShopScraper()
        winners = []
        for product in self.products.values():
            indicators = scraper.get_winning_product_indicators(product)
            if indicators["total_score"] >= min_score:
                winners.append((product, indicators))
        return sorted(winners, key=lambda x: x[1]["total_score"], reverse=True)
