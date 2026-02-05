#!/bin/bash
# TikTok Shop UGC Generator - Setup Script

echo "🛒 TikTok Shop UGC Generator - Setup"
echo "======================================"
echo ""

# Check Python version
python_version=$(python3 --version 2>&1)
if [ $? -ne 0 ]; then
    echo "❌ Python 3 is required but not found."
    echo "   Please install Python 3.9+ and try again."
    exit 1
fi
echo "✓ Found $python_version"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo ""
echo "Creating directories..."
mkdir -p data output/videos output/audio templates

# Copy environment file if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ Created .env file (add your API keys for full functionality)"
fi

# Install playwright browsers (optional)
echo ""
echo "Installing Playwright browsers (for web scraping)..."
playwright install chromium 2>/dev/null || echo "   Skipped Playwright (optional)"

echo ""
echo "======================================"
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env to add your API keys (optional)"
echo "  2. Activate the virtual environment:"
echo "     source venv/bin/activate"
echo "  3. Run the demo:"
echo "     cd src && python main.py demo"
echo ""
echo "Or use the quick run script:"
echo "  ./run.sh demo"
echo "  ./run.sh find-products --category beauty"
echo ""
