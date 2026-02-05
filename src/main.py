#!/usr/bin/env python3
"""
TikTok Shop UGC Generator - Main CLI Interface

Find winning products and create viral UGC videos for TikTok Shop.

Usage:
    python main.py find-products --category beauty --min-sales 100
    python main.py analyze-product --url <product-url>
    python main.py generate-script --product "LED Face Mask" --category beauty
    python main.py create-video --script script.json --images ./images/
    python main.py full-pipeline --product "Product Name" --category beauty
"""

import asyncio
import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

# Import our modules
from config import get_config, validate_api_keys
from scrapers.tiktok_shop import TikTokShopScraper, Product
from scrapers.trend_scraper import TrendScraper, ProductTrendAnalyzer
from scrapers.hashtag_scraper import HashtagScraper
from analyzers.winning_product import (
    WinningProductAnalyzer,
    ProductCandidate,
    BatchProductAnalyzer,
)
from analyzers.competitor import CompetitorAnalyzer
from generators.script_generator import (
    UGCScriptGenerator,
    VideoFormat,
    HookType,
)
from generators.voice_generator import VoiceGenerator
from generators.video_generator import VideoGenerator, QuickVideoCreator
from utils.data_export import export_to_json, export_to_csv, export_product_report

console = Console()


def show_banner():
    """Display the application banner."""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   🛒 TikTok Shop UGC Generator                               ║
║   ────────────────────────────────                           ║
║   Find Winning Products • Create Viral Videos                 ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
    """
    console.print(banner, style="cyan")


def check_setup():
    """Check if the tool is properly configured."""
    api_status = validate_api_keys()

    console.print("\n[bold]🔧 Configuration Status:[/bold]")

    table = Table(show_header=False)
    table.add_column("Service", style="cyan")
    table.add_column("Status")

    for service, configured in api_status.items():
        status = "[green]✓ Configured[/green]" if configured else "[yellow]○ Not configured (optional)[/yellow]"
        table.add_row(service.upper(), status)

    console.print(table)

    if not any(api_status.values()):
        console.print("\n[yellow]ℹ️  No API keys configured. Some features will be limited.[/yellow]")
        console.print("[dim]   Copy .env.example to .env and add your API keys for full functionality.[/dim]")


@click.group()
def cli():
    """TikTok Shop UGC Generator - Find winning products and create viral videos."""
    pass


@cli.command()
@click.option("--category", "-c", default=None, help="Product category to search")
@click.option("--keyword", "-k", default=None, help="Search keyword")
@click.option("--min-sales", default=50, help="Minimum daily sales")
@click.option("--max-results", default=20, help="Maximum results to return")
@click.option("--export", is_flag=True, help="Export results to file")
def find_products(category, keyword, min_sales, max_results, export):
    """Find trending and winning products on TikTok Shop."""
    show_banner()

    async def run():
        console.print(f"\n[bold cyan]🔍 Searching for winning products...[/bold cyan]")

        if category:
            console.print(f"   Category: {category}")
        if keyword:
            console.print(f"   Keyword: {keyword}")
        console.print(f"   Min Sales: {min_sales}/day")
        console.print()

        async with TikTokShopScraper() as scraper:
            products = await scraper.search_trending_products(
                category=category,
                keyword=keyword,
                min_sales=min_sales,
                max_results=max_results,
            )

            # Get trend analysis
            trends = await scraper.analyze_product_trends(days=7)

        # Display trending categories
        console.print("\n[bold]📈 Trending Categories:[/bold]")
        for cat in trends.get("trending_categories", [])[:5]:
            console.print(f"   • {cat['name']}: +{cat['growth']:.1f}%")

        # Display optimal price range
        price_range = trends.get("viral_price_range", {})
        console.print(f"\n[bold]💰 Optimal Price Range:[/bold] ${price_range.get('min', 10)}-${price_range.get('max', 35)}")
        console.print(f"   Sweet spot: ${price_range.get('sweet_spot', 19.99)}")

        # Display top hashtags
        console.print("\n[bold]#️⃣ Top Hashtags:[/bold]")
        for tag in trends.get("top_hashtags", [])[:5]:
            console.print(f"   {tag}")

        if products:
            # Analyze products
            analyzer = WinningProductAnalyzer()

            console.print(f"\n[bold]🏆 Found {len(products)} Products:[/bold]")

            results = []
            for product in products:
                candidate = ProductCandidate(
                    id=product.id,
                    name=product.name,
                    price=product.price,
                    category=category or "general",
                    daily_sales=int(product.sales_velocity),
                    total_sales=product.sales_count,
                    review_count=product.review_count,
                    avg_rating=product.rating,
                    video_count=product.video_count,
                )
                score = analyzer.analyze_product(candidate)
                results.append((product, candidate, score))

            # Sort by score
            results.sort(key=lambda x: x[2].total_score, reverse=True)

            # Display table
            table = Table(title="Product Analysis Results")
            table.add_column("Rank", justify="center")
            table.add_column("Product", style="cyan")
            table.add_column("Price", justify="right")
            table.add_column("Sales/Day", justify="right")
            table.add_column("Score", justify="center")
            table.add_column("Potential")

            for i, (product, candidate, score) in enumerate(results[:10], 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else str(i)
                table.add_row(
                    medal,
                    product.name[:35] + "..." if len(product.name) > 35 else product.name,
                    f"${product.price:.2f}",
                    str(int(product.sales_velocity)),
                    f"{score.total_score}/100",
                    score.potential.value,
                )

            console.print(table)

            if export:
                export_data = [
                    {
                        "name": p.name,
                        "price": p.price,
                        "sales_velocity": p.sales_velocity,
                        "score": s.total_score,
                        "potential": s.potential.value,
                    }
                    for p, _, s in results
                ]
                export_to_csv(export_data, "winning_products")

        else:
            console.print("[yellow]No products found matching criteria[/yellow]")

    asyncio.run(run())


@cli.command()
@click.option("--product", "-p", required=True, help="Product name")
@click.option("--price", type=float, required=True, help="Product price")
@click.option("--category", "-c", required=True, help="Product category")
@click.option("--sales", type=int, default=0, help="Daily sales estimate")
@click.option("--reviews", type=int, default=0, help="Number of reviews")
@click.option("--rating", type=float, default=0.0, help="Average rating")
def analyze_product(product, price, category, sales, reviews, rating):
    """Analyze a product's winning potential."""
    show_banner()

    console.print(f"\n[bold cyan]🔬 Analyzing Product...[/bold cyan]")

    candidate = ProductCandidate(
        id="manual_entry",
        name=product,
        price=price,
        category=category,
        daily_sales=sales,
        review_count=reviews,
        avg_rating=rating,
    )

    analyzer = WinningProductAnalyzer()
    score = analyzer.analyze_product(candidate)

    # Display results
    analyzer.display_analysis(candidate, score)


@cli.command()
@click.option("--product", "-p", required=True, help="Product name")
@click.option("--category", "-c", required=True, help="Product category")
@click.option("--benefits", "-b", multiple=True, help="Product benefits (can specify multiple)")
@click.option("--format", "-f", "video_format", type=click.Choice([
    "problem_solution", "unboxing", "review", "before_after", "tutorial"
]), default="problem_solution", help="Video format")
@click.option("--duration", "-d", type=int, default=30, help="Video duration in seconds")
@click.option("--hook", type=click.Choice([
    "problem", "curiosity", "shock", "social_proof", "direct", "question", "transformation", "challenge"
]), default=None, help="Hook type")
@click.option("--discount-code", default=None, help="Discount code to include")
@click.option("--export", is_flag=True, help="Export script to file")
def generate_script(product, category, benefits, video_format, duration, hook, discount_code, export):
    """Generate a viral UGC video script."""
    show_banner()

    console.print(f"\n[bold cyan]📝 Generating UGC Script...[/bold cyan]")

    # Convert string format to enum
    format_map = {
        "problem_solution": VideoFormat.PROBLEM_SOLUTION,
        "unboxing": VideoFormat.UNBOXING,
        "review": VideoFormat.REVIEW,
        "before_after": VideoFormat.BEFORE_AFTER,
        "tutorial": VideoFormat.TUTORIAL,
    }

    hook_map = {
        "problem": HookType.PROBLEM,
        "curiosity": HookType.CURIOSITY,
        "shock": HookType.SHOCK,
        "social_proof": HookType.SOCIAL_PROOF,
        "direct": HookType.DIRECT,
        "question": HookType.QUESTION,
        "transformation": HookType.TRANSFORMATION,
        "challenge": HookType.CHALLENGE,
    }

    generator = UGCScriptGenerator(use_ai=True)

    script = generator.generate_script(
        product_name=product,
        category=category,
        key_benefits=list(benefits) if benefits else ["amazing quality", "great value", "must-have"],
        video_format=format_map.get(video_format, VideoFormat.PROBLEM_SOLUTION),
        duration=duration,
        hook_type=hook_map.get(hook) if hook else None,
        discount_code=discount_code,
    )

    # Display script
    generator.display_script(script)

    if export:
        export_to_json(script.to_dict(), f"ugc_script_{product.replace(' ', '_')}")


@cli.command()
@click.option("--product", "-p", required=True, help="Product name")
@click.option("--category", "-c", default="general", help="Product category")
def find_trends(product, category):
    """Find trending hashtags and content opportunities."""
    show_banner()

    async def run():
        console.print(f"\n[bold cyan]📈 Finding Trends for {product}...[/bold cyan]")

        # Get trend analysis
        analyzer = ProductTrendAnalyzer()
        opportunities = await analyzer.find_product_opportunities()

        console.print("\n[bold]🔥 Emerging Opportunities:[/bold]")
        for opp in opportunities[:5]:
            console.print(f"\n   Trend: {opp['trend'].get('name', 'Unknown')}")
            console.print(f"   Categories: {', '.join(opp['product_categories'])}")
            console.print(f"   Urgency: {opp['urgency']}")
            console.print(f"   Action: {opp['recommended_action']}")

        # Get hashtags
        scraper = HashtagScraper()
        optimal_hashtags = scraper.get_optimal_hashtag_set(category, "general")

        console.print(f"\n[bold]#️⃣ Recommended Hashtags for {category}:[/bold]")
        console.print("   " + " ".join([f"#{tag}" for tag in optimal_hashtags]))

        # Get trending hashtags
        async with TrendScraper() as trend_scraper:
            trending = await trend_scraper.get_trending_hashtags(category=category, limit=10)

            if trending:
                console.print("\n[bold]📊 Trending in Category:[/bold]")
                for h in trending[:5]:
                    console.print(f"   {h.name}")

    asyncio.run(run())


@cli.command()
@click.option("--script-file", "-s", type=click.Path(exists=True), required=True, help="Script JSON file")
@click.option("--images-dir", "-i", type=click.Path(exists=True), required=True, help="Directory with images")
@click.option("--output-name", "-o", default="ugc_video", help="Output video name")
@click.option("--music", "-m", type=click.Path(exists=True), default=None, help="Background music file")
def create_video(script_file, images_dir, output_name, music):
    """Create a video from a script and images."""
    show_banner()

    import json

    async def run():
        console.print(f"\n[bold cyan]🎬 Creating Video...[/bold cyan]")

        # Load script
        with open(script_file, "r") as f:
            script = json.load(f)

        # Get images
        images_path = Path(images_dir)
        images = list(images_path.glob("*.png")) + list(images_path.glob("*.jpg")) + list(images_path.glob("*.jpeg"))

        if not images:
            console.print("[red]No images found in directory![/red]")
            return

        console.print(f"   Found {len(images)} images")

        # Generate voiceover
        voice_gen = VoiceGenerator()
        audio_files = []

        if voice_gen.available_providers:
            console.print("[cyan]Generating voiceover...[/cyan]")
            sections = script.get("sections", [])
            audio_files = await voice_gen.generate_script_audio(
                sections, output_name
            )

        # Create video
        video_gen = VideoGenerator()
        video_path = await video_gen.create_video_from_script(
            script=script,
            images=images,
            audio_files=audio_files,
            background_music=Path(music) if music else None,
            output_name=output_name,
        )

        if video_path:
            console.print(f"\n[bold green]✓ Video created: {video_path}[/bold green]")
        else:
            console.print("[red]Video creation failed[/red]")

    asyncio.run(run())


@cli.command()
@click.option("--product", "-p", required=True, help="Product name")
@click.option("--category", "-c", required=True, help="Product category")
@click.option("--benefits", "-b", multiple=True, required=True, help="Product benefits")
@click.option("--price", type=float, required=True, help="Product price")
@click.option("--images-dir", "-i", type=click.Path(exists=True), required=True, help="Product images directory")
@click.option("--format", "-f", "video_format", default="problem_solution", help="Video format")
def full_pipeline(product, category, benefits, price, images_dir, video_format):
    """Run the full pipeline: analyze → script → voice → video."""
    show_banner()

    async def run():
        console.print(Panel(
            f"[bold]Running Full Pipeline[/bold]\n\n"
            f"Product: {product}\n"
            f"Category: {category}\n"
            f"Price: ${price}\n"
            f"Benefits: {', '.join(benefits)}",
            title="🚀 TikTok Shop UGC Generator",
            border_style="cyan",
        ))

        # Step 1: Analyze product
        console.print("\n[bold]Step 1/4: Analyzing Product[/bold]")
        candidate = ProductCandidate(
            id="pipeline",
            name=product,
            price=price,
            category=category,
        )

        analyzer = WinningProductAnalyzer()
        score = analyzer.analyze_product(candidate)
        console.print(f"   Score: {score.total_score}/100 - {score.potential.value}")

        # Step 2: Generate script
        console.print("\n[bold]Step 2/4: Generating Script[/bold]")
        format_map = {
            "problem_solution": VideoFormat.PROBLEM_SOLUTION,
            "unboxing": VideoFormat.UNBOXING,
            "review": VideoFormat.REVIEW,
        }

        script_gen = UGCScriptGenerator()
        script = script_gen.generate_script(
            product_name=product,
            category=category,
            key_benefits=list(benefits),
            video_format=format_map.get(video_format, VideoFormat.PROBLEM_SOLUTION),
            duration=30,
        )
        console.print(f"   ✓ Script generated: {script.title}")

        # Step 3: Generate voiceover
        console.print("\n[bold]Step 3/4: Generating Voiceover[/bold]")
        voice_gen = VoiceGenerator()
        audio_files = []

        if voice_gen.available_providers:
            audio_files = await voice_gen.generate_script_audio(
                [{"text": s.text} for s in script.sections],
                product.replace(" ", "_"),
            )
            console.print(f"   ✓ Generated {len(audio_files)} audio segments")
        else:
            console.print("   [yellow]No voice providers available - skipping voiceover[/yellow]")

        # Step 4: Create video
        console.print("\n[bold]Step 4/4: Creating Video[/bold]")

        images_path = Path(images_dir)
        images = list(images_path.glob("*.png")) + list(images_path.glob("*.jpg"))

        if not images:
            console.print("   [red]No images found - cannot create video[/red]")
            return

        video_gen = VideoGenerator()
        video_path = await video_gen.create_video_from_script(
            script=script.to_dict(),
            images=images,
            audio_files=audio_files,
            output_name=product.replace(" ", "_"),
        )

        if video_path:
            console.print(f"\n[bold green]{'='*50}[/bold green]")
            console.print(f"[bold green]✓ PIPELINE COMPLETE![/bold green]")
            console.print(f"[bold green]{'='*50}[/bold green]")
            console.print(f"\n   Video saved: {video_path}")
            console.print(f"   Duration: {script.total_duration}s")
            console.print(f"\n[bold]📱 Caption:[/bold]")
            console.print(f"   {script.caption}")

        # Export script
        export_to_json(script.to_dict(), f"{product.replace(' ', '_')}_script")

    asyncio.run(run())


@cli.command()
def setup():
    """Check configuration and setup status."""
    show_banner()
    check_setup()

    console.print("\n[bold]📁 Directory Structure:[/bold]")
    dirs = ["./data", "./output/videos", "./output/audio", "./templates"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
        console.print(f"   [green]✓[/green] {d}")

    console.print("\n[bold]Next Steps:[/bold]")
    console.print("   1. Copy .env.example to .env")
    console.print("   2. Add your API keys (optional but recommended)")
    console.print("   3. Run: python main.py find-products --category beauty")
    console.print()


@cli.command()
def demo():
    """Run a demo to see the tool in action."""
    show_banner()

    console.print("\n[bold cyan]🎯 Running Demo...[/bold cyan]")

    # Generate sample script
    generator = UGCScriptGenerator(use_ai=False)

    script = generator.generate_script(
        product_name="LED Face Mask",
        category="beauty",
        key_benefits=["reduces wrinkles", "clears acne", "5-minute treatment"],
        video_format=VideoFormat.PROBLEM_SOLUTION,
        duration=30,
        discount_code="GLOW15",
    )

    console.print("\n[bold]📝 Sample UGC Script:[/bold]")
    generator.display_script(script)

    # Show analysis for sample product
    console.print("\n[bold]🔬 Sample Product Analysis:[/bold]")

    candidate = ProductCandidate(
        id="demo",
        name="LED Face Mask",
        price=29.99,
        category="beauty",
        daily_sales=150,
        total_sales=4500,
        review_count=320,
        avg_rating=4.6,
        video_count=85,
        total_views=2500000,
    )

    analyzer = WinningProductAnalyzer()
    score = analyzer.analyze_product(candidate)
    analyzer.display_analysis(candidate, score)

    console.print("\n[bold green]Demo complete![/bold green]")
    console.print("[dim]Run 'python main.py --help' to see all available commands.[/dim]")


if __name__ == "__main__":
    cli()
