"""Helper utilities for the UGC generator."""

import os
import re
from pathlib import Path
from datetime import datetime


def format_number(num: int) -> str:
    """Format large numbers for display (e.g., 1.5M, 10K)."""
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be used as a filename."""
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')
    # Limit length
    sanitized = sanitized[:100]
    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip('. ')
    return sanitized or "unnamed"


def create_directory(path: str) -> Path:
    """Create a directory if it doesn't exist."""
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def get_timestamp() -> str:
    """Get current timestamp string for filenames."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def calculate_engagement_rate(likes: int, comments: int, shares: int, views: int) -> float:
    """Calculate engagement rate percentage."""
    if views == 0:
        return 0.0
    return ((likes + comments + shares) / views) * 100


def estimate_profit_margin(selling_price: float, product_cost: float, shipping_cost: float = 0) -> float:
    """Calculate profit margin percentage."""
    total_cost = product_cost + shipping_cost
    if selling_price == 0:
        return 0.0
    profit = selling_price - total_cost
    return (profit / selling_price) * 100


def is_winning_price_point(price: float) -> bool:
    """Check if price is in the optimal range for impulse buys."""
    return 15 <= price <= 35


def calculate_roi(revenue: float, ad_spend: float) -> float:
    """Calculate return on investment."""
    if ad_spend == 0:
        return 0.0
    return ((revenue - ad_spend) / ad_spend) * 100


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max length with suffix."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def parse_hashtags(text: str) -> list[str]:
    """Extract hashtags from text."""
    return re.findall(r'#(\w+)', text)


def format_duration(seconds: float) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def validate_url(url: str) -> bool:
    """Basic URL validation."""
    pattern = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )
    return bool(pattern.match(url))


def get_file_size(file_path: Path) -> str:
    """Get human-readable file size."""
    if not file_path.exists():
        return "0 B"

    size = file_path.stat().st_size
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
