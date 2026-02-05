"""
Video generation for UGC content.

Creates TikTok-optimized videos with text overlays, transitions, and effects.
"""

import asyncio
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Union
from enum import Enum
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class VideoAspectRatio(Enum):
    """Video aspect ratios."""
    TIKTOK = (1080, 1920)  # 9:16
    INSTAGRAM_REEL = (1080, 1920)  # 9:16
    YOUTUBE_SHORT = (1080, 1920)  # 9:16
    SQUARE = (1080, 1080)  # 1:1
    LANDSCAPE = (1920, 1080)  # 16:9


class TextPosition(Enum):
    """Text overlay positions."""
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


@dataclass
class TextOverlay:
    """Text overlay configuration."""
    text: str
    position: TextPosition = TextPosition.CENTER
    font_size: int = 48
    font_color: str = "white"
    background_color: Optional[str] = "black"
    background_opacity: float = 0.7
    start_time: float = 0
    end_time: Optional[float] = None
    animation: str = "fade"  # fade, slide, pop


@dataclass
class VideoClip:
    """A video clip segment."""
    source: Union[str, Path]  # Video file path or image path
    duration: float
    start_trim: float = 0
    end_trim: Optional[float] = None
    text_overlays: list[TextOverlay] = field(default_factory=list)
    audio_path: Optional[Path] = None
    transition: str = "fade"  # fade, slide, cut


@dataclass
class VideoProject:
    """Complete video project."""
    name: str
    clips: list[VideoClip] = field(default_factory=list)
    background_music: Optional[Path] = None
    music_volume: float = 0.3
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.TIKTOK
    output_path: Optional[Path] = None


class VideoGenerator:
    """
    Generates UGC-style videos for TikTok.

    Features:
    - Text overlays with animations
    - Automatic caption generation
    - Background music mixing
    - Transitions between clips
    - TikTok-optimized output (9:16, 1080x1920)
    """

    # TikTok-style fonts (system fallbacks)
    FONTS = {
        "bold": "Arial-Bold",
        "regular": "Arial",
        "handwritten": "Comic Sans MS",
        "modern": "Helvetica",
    }

    # Color presets
    COLORS = {
        "tiktok_pink": "#FF0050",
        "tiktok_cyan": "#00F2EA",
        "white": "#FFFFFF",
        "black": "#000000",
        "yellow": "#FFFC00",
        "green": "#00FF00",
    }

    def __init__(self, output_dir: str = "./output/videos"):
        """Initialize the video generator."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._check_dependencies()

    def _check_dependencies(self):
        """Check if required video libraries are available."""
        self.moviepy_available = False
        self.pillow_available = False

        try:
            import moviepy.editor
            self.moviepy_available = True
        except ImportError:
            console.print("[yellow]MoviePy not available - install with: pip install moviepy[/yellow]")

        try:
            from PIL import Image
            self.pillow_available = True
        except ImportError:
            console.print("[yellow]Pillow not available - install with: pip install Pillow[/yellow]")

    async def create_video_from_script(
        self,
        script: dict,
        images: list[Path],
        audio_files: list[Path],
        background_music: Optional[Path] = None,
        output_name: str = "ugc_video"
    ) -> Optional[Path]:
        """
        Create a video from a UGC script, images, and audio.

        Args:
            script: UGC script dictionary with sections
            images: List of image paths for each section
            audio_files: List of audio files for voiceover
            background_music: Optional background music path
            output_name: Name for output video file

        Returns:
            Path to generated video or None if failed
        """
        if not self.moviepy_available:
            console.print("[red]MoviePy is required for video generation[/red]")
            return None

        from moviepy.editor import (
            ImageClip, AudioFileClip, CompositeVideoClip,
            concatenate_videoclips, CompositeAudioClip, TextClip
        )

        console.print("[cyan]🎬 Creating video from script...[/cyan]")

        clips = []
        sections = script.get("sections", [])

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Processing sections...", total=len(sections))

            for i, section in enumerate(sections):
                duration = section.get("duration", 5)

                # Get image for this section (cycle if not enough images)
                image_path = images[i % len(images)] if images else None

                # Get audio for this section
                audio_path = audio_files[i] if i < len(audio_files) else None

                if image_path:
                    # Create image clip
                    clip = ImageClip(str(image_path), duration=duration)

                    # Resize to TikTok dimensions
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080)
                    elif clip.w < 1080:
                        # Add black bars
                        clip = clip.on_color(
                            size=(1080, 1920),
                            color=(0, 0, 0),
                            pos="center"
                        )

                    # Add text overlay
                    text = section.get("text", "")
                    if text:
                        txt_clip = self._create_text_overlay(text, duration)
                        clip = CompositeVideoClip([clip, txt_clip])

                    # Add audio
                    if audio_path and Path(audio_path).exists():
                        audio = AudioFileClip(str(audio_path))
                        if audio.duration < duration:
                            clip = clip.set_duration(audio.duration)
                        clip = clip.set_audio(audio)

                    clips.append(clip)

                progress.update(task, advance=1)

        if not clips:
            console.print("[red]No clips generated![/red]")
            return None

        # Concatenate all clips
        console.print("[cyan]Combining clips...[/cyan]")
        final_video = concatenate_videoclips(clips, method="compose")

        # Add background music if provided
        if background_music and Path(background_music).exists():
            console.print("[cyan]Adding background music...[/cyan]")
            bg_music = AudioFileClip(str(background_music))
            bg_music = bg_music.volumex(0.2)  # Lower volume

            if bg_music.duration < final_video.duration:
                bg_music = bg_music.loop(duration=final_video.duration)
            else:
                bg_music = bg_music.subclip(0, final_video.duration)

            if final_video.audio:
                final_audio = CompositeAudioClip([final_video.audio, bg_music])
                final_video = final_video.set_audio(final_audio)
            else:
                final_video = final_video.set_audio(bg_music)

        # Export
        output_path = self.output_dir / f"{output_name}.mp4"
        console.print(f"[cyan]Exporting video to {output_path}...[/cyan]")

        final_video.write_videofile(
            str(output_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            preset="medium",
            verbose=False,
            logger=None,
        )

        # Clean up
        final_video.close()
        for clip in clips:
            clip.close()

        console.print(f"[green]✓ Video saved: {output_path}[/green]")
        return output_path

    def _create_text_overlay(
        self,
        text: str,
        duration: float,
        position: str = "center",
        font_size: int = 40
    ):
        """Create a text overlay clip."""
        from moviepy.editor import TextClip

        # Wrap text for TikTok dimensions
        max_chars = 35
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            if len(" ".join(current_line + [word])) <= max_chars:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        wrapped_text = "\n".join(lines)

        txt_clip = TextClip(
            wrapped_text,
            fontsize=font_size,
            color="white",
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(1000, None),
            align="center",
        )

        txt_clip = txt_clip.set_position(("center", "center"))
        txt_clip = txt_clip.set_duration(duration)

        # Add fade in/out
        txt_clip = txt_clip.crossfadein(0.3).crossfadeout(0.3)

        return txt_clip

    async def create_slideshow_video(
        self,
        images: list[Path],
        durations: list[float],
        texts: list[str],
        audio_path: Optional[Path] = None,
        output_name: str = "slideshow"
    ) -> Optional[Path]:
        """
        Create a simple slideshow video from images.

        Good for quick product showcases.
        """
        if not self.moviepy_available:
            console.print("[red]MoviePy required for video generation[/red]")
            return None

        from moviepy.editor import (
            ImageClip, concatenate_videoclips, CompositeVideoClip, AudioFileClip
        )

        console.print("[cyan]🎬 Creating slideshow video...[/cyan]")

        clips = []

        for i, (image, duration, text) in enumerate(zip(images, durations, texts)):
            if not Path(image).exists():
                continue

            # Create clip
            clip = ImageClip(str(image), duration=duration)
            clip = clip.resize(height=1920)

            # Crop or pad to 9:16
            if clip.w > 1080:
                clip = clip.crop(x_center=clip.w/2, width=1080)
            elif clip.w < 1080:
                clip = clip.on_color(size=(1080, 1920), color=(0, 0, 0), pos="center")

            # Add text
            if text:
                txt_clip = self._create_text_overlay(text, duration)
                clip = CompositeVideoClip([clip, txt_clip])

            # Add transitions
            if i > 0:
                clip = clip.crossfadein(0.3)

            clips.append(clip)

        if not clips:
            return None

        final = concatenate_videoclips(clips, method="compose")

        # Add audio
        if audio_path and Path(audio_path).exists():
            audio = AudioFileClip(str(audio_path))
            if audio.duration != final.duration:
                final = final.set_duration(min(final.duration, audio.duration))
            final = final.set_audio(audio)

        output_path = self.output_dir / f"{output_name}.mp4"
        final.write_videofile(
            str(output_path),
            fps=30,
            codec="libx264",
            verbose=False,
            logger=None,
        )

        final.close()
        console.print(f"[green]✓ Video saved: {output_path}[/green]")
        return output_path

    async def add_captions_to_video(
        self,
        video_path: Path,
        captions: list[dict],
        output_name: str = "captioned_video"
    ) -> Optional[Path]:
        """
        Add auto-captions to an existing video.

        captions format: [{"start": 0, "end": 3, "text": "Hello"}, ...]
        """
        if not self.moviepy_available:
            return None

        from moviepy.editor import VideoFileClip, CompositeVideoClip

        console.print("[cyan]Adding captions to video...[/cyan]")

        video = VideoFileClip(str(video_path))
        caption_clips = []

        for caption in captions:
            start = caption["start"]
            end = caption["end"]
            text = caption["text"]

            txt_clip = self._create_text_overlay(text, end - start)
            txt_clip = txt_clip.set_start(start)
            txt_clip = txt_clip.set_position(("center", 0.75), relative=True)
            caption_clips.append(txt_clip)

        final = CompositeVideoClip([video] + caption_clips)

        output_path = self.output_dir / f"{output_name}.mp4"
        final.write_videofile(
            str(output_path),
            fps=video.fps,
            codec="libx264",
            verbose=False,
            logger=None,
        )

        video.close()
        final.close()

        console.print(f"[green]✓ Captioned video saved: {output_path}[/green]")
        return output_path

    def generate_thumbnail(
        self,
        video_path: Path,
        timestamp: float = 0,
        output_name: str = "thumbnail"
    ) -> Optional[Path]:
        """Generate a thumbnail from a video."""
        if not self.moviepy_available:
            return None

        from moviepy.editor import VideoFileClip

        video = VideoFileClip(str(video_path))
        frame = video.get_frame(timestamp)

        output_path = self.output_dir / f"{output_name}.png"

        if self.pillow_available:
            from PIL import Image
            img = Image.fromarray(frame)
            img.save(str(output_path))
            console.print(f"[green]✓ Thumbnail saved: {output_path}[/green]")
            return output_path

        video.close()
        return None


class QuickVideoCreator:
    """
    Simplified video creation for rapid UGC production.

    Use this for quick, template-based videos.
    """

    def __init__(self):
        """Initialize quick creator."""
        self.generator = VideoGenerator()

    async def create_product_showcase(
        self,
        product_images: list[Path],
        product_name: str,
        benefits: list[str],
        price: str,
        audio_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Create a quick product showcase video.

        Structure:
        1. Product reveal
        2. Benefits showcase
        3. Price/CTA
        """
        texts = [
            f"Check out this {product_name}! 👀",
            *[f"✨ {benefit}" for benefit in benefits[:3]],
            f"Only {price}! Link in bio 🔗",
        ]

        durations = [3.0] + [4.0] * min(3, len(benefits)) + [3.0]

        # Ensure enough images
        while len(product_images) < len(texts):
            product_images.append(product_images[-1])

        return await self.generator.create_slideshow_video(
            images=product_images[:len(texts)],
            durations=durations[:len(texts)],
            texts=texts,
            audio_path=audio_path,
            output_name=f"{product_name.replace(' ', '_')}_showcase",
        )

    async def create_before_after(
        self,
        before_image: Path,
        after_image: Path,
        product_name: str,
        transformation_text: str,
        audio_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """Create a before/after transformation video."""
        return await self.generator.create_slideshow_video(
            images=[before_image, after_image, after_image],
            durations=[3.0, 3.0, 4.0],
            texts=[
                "Before ❌",
                "After using " + product_name + " ✨",
                transformation_text + " 🔗 Link in bio!"
            ],
            audio_path=audio_path,
            output_name=f"{product_name.replace(' ', '_')}_transformation",
        )
