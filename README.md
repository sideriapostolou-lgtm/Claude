# 🛒 TikTok Shop UGC Generator

Find winning products on TikTok Shop and automatically create viral UGC (User Generated Content) videos.

## Features

- **🔍 Product Research**: Find trending and winning products on TikTok Shop
- **📊 Winning Product Analysis**: Score products based on viral potential, profit margins, demand, and competition
- **📈 Trend Detection**: Identify emerging trends before they go viral
- **📝 UGC Script Generation**: Create proven viral video scripts (problem-solution, unboxing, review, etc.)
- **🎙️ Voice Generation**: Generate natural voiceovers using multiple TTS providers
- **🎬 Video Creation**: Automatically create TikTok-optimized videos with text overlays
- **#️⃣ Hashtag Optimization**: Get optimal hashtag combinations for maximum reach

## Quick Start

### 1. Install Dependencies

```bash
# Navigate to project directory
cd Claude

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for web scraping)
playwright install chromium
```

### 2. Configure API Keys (Optional but Recommended)

```bash
# Copy example configuration
cp .env.example .env

# Edit .env and add your API keys
```

**Supported APIs:**
- **OpenAI** - For AI-powered script generation
- **Anthropic** - Alternative AI provider
- **ElevenLabs** - Premium voice generation
- **Stability AI** - Image generation

> Note: The tool works without API keys using free alternatives (Edge TTS, template-based scripts)

### 3. Run Setup Check

```bash
cd src
python main.py setup
```

### 4. Start Finding Winners!

```bash
# Find winning products in beauty category
python main.py find-products --category beauty --min-sales 100

# Run a demo to see the tool in action
python main.py demo
```

## Usage

### Find Winning Products

```bash
# Search by category
python main.py find-products --category beauty

# Search by keyword
python main.py find-products --keyword "led mask"

# Filter by minimum sales
python main.py find-products --category home --min-sales 50

# Export results
python main.py find-products --category tech --export
```

### Analyze a Product

```bash
python main.py analyze-product \
  --product "LED Face Mask" \
  --price 29.99 \
  --category beauty \
  --sales 150 \
  --reviews 320 \
  --rating 4.6
```

### Generate UGC Script

```bash
# Basic script generation
python main.py generate-script \
  --product "LED Face Mask" \
  --category beauty \
  --benefits "reduces wrinkles" \
  --benefits "clears acne" \
  --benefits "5-minute treatment"

# With specific format and hook
python main.py generate-script \
  --product "Kitchen Organizer" \
  --category home \
  --format unboxing \
  --hook curiosity \
  --duration 45

# With discount code
python main.py generate-script \
  --product "Phone Stand" \
  --category tech \
  --discount-code SAVE15
```

### Find Trending Hashtags

```bash
python main.py find-trends --product "skincare" --category beauty
```

### Create Video (Requires images)

```bash
python main.py create-video \
  --script-file output/ugc_script.json \
  --images-dir ./product_images/ \
  --output-name my_ugc_video \
  --music ./background_music.mp3
```

### Full Pipeline (Analyze → Script → Voice → Video)

```bash
python main.py full-pipeline \
  --product "LED Face Mask" \
  --category beauty \
  --benefits "reduces wrinkles" \
  --benefits "clears acne" \
  --price 29.99 \
  --images-dir ./product_images/
```

## Winning Product Criteria

The analyzer scores products based on:

| Factor | Weight | What It Measures |
|--------|--------|------------------|
| Virality | 20% | Video engagement, existing content, hashtag momentum |
| Profit | 20% | Margin potential, price optimization, impulse buy appeal |
| Demand | 20% | Sales velocity, trends, review validation |
| Competition | 15% | Seller count, market concentration, entry barriers |
| Content | 15% | UGC creation potential, demonstrability |
| Timing | 10% | Trend lifecycle stage, seasonal relevance |

**Score Interpretation:**
- 🏆 **80-100**: Winner - Take action immediately
- ⭐ **65-79**: High Potential - Worth pursuing
- 📈 **50-64**: Rising - Monitor and test
- 👀 **35-49**: Watch - Needs more validation
- ⏭️ **0-34**: Skip - Better opportunities exist

## Video Formats

| Format | Best For | Structure |
|--------|----------|-----------|
| Problem-Solution | Most products | Hook → Problem → Solution → Demo → CTA |
| Unboxing | New/exciting products | Anticipation → Reveal → First impression → CTA |
| Review | Established products | Hook → Background → Pros/Cons → Verdict → CTA |
| Before/After | Transformation products | Before → Process → Reveal → CTA |
| Tutorial | How-to products | Hook → Steps → Results → CTA |

## Hook Types

| Hook | When to Use | Example |
|------|-------------|---------|
| Problem | Solving pain points | "Stop scrolling if you struggle with..." |
| Curiosity | New/unique products | "Wait until you see this..." |
| Shock | Amazing results | "I literally gasped when I tried this" |
| Social Proof | Popular products | "Everyone keeps asking about this" |
| Direct | Confident sells | "You need this immediately" |
| Question | Engaging audience | "Have you ever wished there was..." |
| Transformation | Before/after | "Watch this transformation" |
| Challenge | Testing products | "I tested the viral product so you don't have to" |

## Project Structure

```
Claude/
├── src/
│   ├── main.py              # CLI interface
│   ├── config.py            # Configuration
│   ├── scrapers/
│   │   ├── tiktok_shop.py   # Product scraping
│   │   ├── trend_scraper.py # Trend analysis
│   │   └── hashtag_scraper.py
│   ├── analyzers/
│   │   ├── winning_product.py # Product scoring
│   │   └── competitor.py
│   ├── generators/
│   │   ├── script_generator.py # UGC scripts
│   │   ├── voice_generator.py  # TTS
│   │   └── video_generator.py  # Video creation
│   └── utils/
│       ├── helpers.py
│       └── data_export.py
├── data/                    # Stored data
├── output/                  # Generated content
│   ├── videos/
│   └── audio/
├── templates/               # Script templates
├── requirements.txt
├── .env.example
└── README.md
```

## Tips for Viral Success

1. **Hook in 1-3 seconds** - Prevent the scroll
2. **Show, don't tell** - Demonstrate the product in action
3. **Use trending sounds** - Increases discoverability
4. **Native feel** - Avoid looking like an ad
5. **Strong CTA** - Clear call to action with urgency
6. **Optimal pricing** - $15-35 sweet spot for impulse buys
7. **Post timing** - 6-8 AM, 12-2 PM, 7-9 PM
8. **Hashtag mix** - 2 broad + 2-3 niche hashtags

## Troubleshooting

### No products found
- Try different categories or keywords
- Lower the minimum sales threshold
- Check your internet connection

### Video generation fails
- Ensure MoviePy is installed: `pip install moviepy`
- Install FFmpeg on your system
- Check image files are valid PNG/JPG

### Voice generation not working
- Check if Edge TTS is installed: `pip install edge-tts`
- Or configure ElevenLabs/OpenAI API keys

## License

MIT License - Feel free to use and modify for your needs.

## Support

For issues or feature requests, please open an issue on GitHub.

---

**Disclaimer**: This tool is for educational purposes. Always follow TikTok's Terms of Service and guidelines when creating content.
