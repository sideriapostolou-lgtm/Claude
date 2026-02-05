"""Configuration management for TikTok Shop UGC Generator."""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class APIConfig(BaseModel):
    """API configuration settings."""
    openai_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    anthropic_key: Optional[str] = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    elevenlabs_key: Optional[str] = Field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY"))
    stability_key: Optional[str] = Field(default_factory=lambda: os.getenv("STABILITY_API_KEY"))
    tiktok_client_key: Optional[str] = Field(default_factory=lambda: os.getenv("TIKTOK_CLIENT_KEY"))
    tiktok_client_secret: Optional[str] = Field(default_factory=lambda: os.getenv("TIKTOK_CLIENT_SECRET"))


class ScrapingConfig(BaseModel):
    """Scraping configuration settings."""
    delay: float = Field(default=2.0)
    max_products: int = Field(default=50)
    timeout: int = Field(default=30)
    retry_attempts: int = Field(default=3)
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    )


class VideoConfig(BaseModel):
    """Video generation configuration."""
    output_dir: Path = Field(default=Path("./output/videos"))
    quality: str = Field(default="high")
    resolution: tuple = Field(default=(1080, 1920))  # 9:16 for TikTok
    fps: int = Field(default=30)
    default_voice: str = Field(default="en-US-ChristopherNeural")
    max_duration: int = Field(default=60)  # seconds


class WinningProductCriteria(BaseModel):
    """Criteria for identifying winning products."""
    min_sales_velocity: int = Field(default=100)  # sales per day
    min_reviews: int = Field(default=50)
    min_rating: float = Field(default=4.0)
    max_price: float = Field(default=50.0)
    min_profit_margin: float = Field(default=0.3)  # 30%
    trending_hashtag_threshold: int = Field(default=1000000)  # views


class Config(BaseModel):
    """Main configuration class."""
    api: APIConfig = Field(default_factory=APIConfig)
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    winning_criteria: WinningProductCriteria = Field(default_factory=WinningProductCriteria)

    class Config:
        arbitrary_types_allowed = True


# Global config instance
config = Config()


def get_config() -> Config:
    """Get the global configuration instance."""
    return config


def validate_api_keys() -> dict:
    """Validate which API keys are configured."""
    return {
        "openai": bool(config.api.openai_key),
        "anthropic": bool(config.api.anthropic_key),
        "elevenlabs": bool(config.api.elevenlabs_key),
        "stability": bool(config.api.stability_key),
    }
