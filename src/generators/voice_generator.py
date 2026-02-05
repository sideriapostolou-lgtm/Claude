"""
Voice generation for UGC videos.

Supports multiple TTS providers for natural voiceovers.
"""

import asyncio
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from enum import Enum
from rich.console import Console

console = Console()


class VoiceProvider(Enum):
    """Supported voice providers."""
    EDGE_TTS = "edge_tts"  # Free, Microsoft Edge voices
    ELEVENLABS = "elevenlabs"  # Premium, most realistic
    GTTS = "gtts"  # Free, Google TTS
    OPENAI = "openai"  # OpenAI TTS


@dataclass
class VoiceConfig:
    """Configuration for voice generation."""
    provider: VoiceProvider
    voice_id: str
    speed: float = 1.0
    pitch: float = 1.0
    output_format: str = "mp3"


class VoiceGenerator:
    """
    Generates voiceovers for UGC content.

    Supported providers:
    - Edge TTS (free, good quality)
    - ElevenLabs (premium, best quality)
    - Google TTS (free, basic)
    - OpenAI TTS (good quality)
    """

    # Recommended voices for UGC content
    RECOMMENDED_VOICES = {
        VoiceProvider.EDGE_TTS: {
            "female_us": "en-US-JennyNeural",
            "female_us_casual": "en-US-AriaNeural",
            "male_us": "en-US-GuyNeural",
            "male_us_casual": "en-US-ChristopherNeural",
            "female_uk": "en-GB-SoniaNeural",
            "male_uk": "en-GB-RyanNeural",
        },
        VoiceProvider.ELEVENLABS: {
            "female_young": "21m00Tcm4TlvDq8ikWAM",  # Rachel
            "female_middle": "AZnzlk1XvdvUeBnXmlld",  # Domi
            "male_young": "VR6AewLTigWG4xSOukaG",  # Arnold
            "male_middle": "pNInz6obpgDQGcFmaJgB",  # Adam
        },
        VoiceProvider.OPENAI: {
            "alloy": "alloy",
            "echo": "echo",
            "fable": "fable",
            "onyx": "onyx",
            "nova": "nova",
            "shimmer": "shimmer",
        },
    }

    def __init__(self, output_dir: str = "./output/audio"):
        """Initialize the voice generator."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check available providers
        self.available_providers = self._check_providers()

    def _check_providers(self) -> list[VoiceProvider]:
        """Check which voice providers are available."""
        available = []

        # Edge TTS (free, always available if package installed)
        try:
            import edge_tts
            available.append(VoiceProvider.EDGE_TTS)
        except ImportError:
            pass

        # ElevenLabs (needs API key)
        if os.getenv("ELEVENLABS_API_KEY"):
            available.append(VoiceProvider.ELEVENLABS)

        # Google TTS (free)
        try:
            from gtts import gTTS
            available.append(VoiceProvider.GTTS)
        except ImportError:
            pass

        # OpenAI TTS (needs API key)
        if os.getenv("OPENAI_API_KEY"):
            available.append(VoiceProvider.OPENAI)

        return available

    def get_best_provider(self) -> Optional[VoiceProvider]:
        """Get the best available voice provider."""
        # Priority: ElevenLabs > OpenAI > Edge TTS > gTTS
        priority = [
            VoiceProvider.ELEVENLABS,
            VoiceProvider.OPENAI,
            VoiceProvider.EDGE_TTS,
            VoiceProvider.GTTS,
        ]

        for provider in priority:
            if provider in self.available_providers:
                return provider

        return None

    async def generate_voice(
        self,
        text: str,
        output_filename: str,
        provider: Optional[VoiceProvider] = None,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
    ) -> Optional[Path]:
        """
        Generate voiceover audio from text.

        Args:
            text: Text to convert to speech
            output_filename: Name of output file (without extension)
            provider: Voice provider to use (auto-selects if None)
            voice_id: Specific voice to use
            speed: Speech speed multiplier

        Returns:
            Path to generated audio file, or None if failed
        """
        if not provider:
            provider = self.get_best_provider()

        if not provider:
            console.print("[red]No voice provider available![/red]")
            return None

        console.print(f"[cyan]🎙️ Generating voice with {provider.value}...[/cyan]")

        output_path = self.output_dir / f"{output_filename}.mp3"

        try:
            if provider == VoiceProvider.EDGE_TTS:
                return await self._generate_edge_tts(text, output_path, voice_id, speed)
            elif provider == VoiceProvider.ELEVENLABS:
                return await self._generate_elevenlabs(text, output_path, voice_id)
            elif provider == VoiceProvider.GTTS:
                return await self._generate_gtts(text, output_path)
            elif provider == VoiceProvider.OPENAI:
                return await self._generate_openai(text, output_path, voice_id, speed)
        except Exception as e:
            console.print(f"[red]Voice generation failed: {e}[/red]")
            return None

    async def _generate_edge_tts(
        self,
        text: str,
        output_path: Path,
        voice_id: Optional[str],
        speed: float
    ) -> Path:
        """Generate voice using Edge TTS (free)."""
        import edge_tts

        voice = voice_id or "en-US-AriaNeural"
        rate = f"{int((speed - 1) * 100):+d}%"

        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(output_path))

        console.print(f"[green]✓ Generated: {output_path}[/green]")
        return output_path

    async def _generate_elevenlabs(
        self,
        text: str,
        output_path: Path,
        voice_id: Optional[str]
    ) -> Path:
        """Generate voice using ElevenLabs (premium quality)."""
        import httpx

        api_key = os.getenv("ELEVENLABS_API_KEY")
        voice = voice_id or "21m00Tcm4TlvDq8ikWAM"  # Rachel

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_monolingual_v1",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    }
                },
                timeout=60.0,
            )

            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                console.print(f"[green]✓ Generated: {output_path}[/green]")
                return output_path
            else:
                raise Exception(f"ElevenLabs API error: {response.status_code}")

    async def _generate_gtts(self, text: str, output_path: Path) -> Path:
        """Generate voice using Google TTS (free, basic)."""
        from gtts import gTTS

        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(str(output_path))

        console.print(f"[green]✓ Generated: {output_path}[/green]")
        return output_path

    async def _generate_openai(
        self,
        text: str,
        output_path: Path,
        voice_id: Optional[str],
        speed: float
    ) -> Path:
        """Generate voice using OpenAI TTS."""
        from openai import OpenAI

        client = OpenAI()
        voice = voice_id or "nova"

        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=text,
            speed=speed,
        )

        response.stream_to_file(str(output_path))

        console.print(f"[green]✓ Generated: {output_path}[/green]")
        return output_path

    async def generate_script_audio(
        self,
        script_sections: list[dict],
        base_filename: str,
        provider: Optional[VoiceProvider] = None,
    ) -> list[Path]:
        """
        Generate audio for all sections of a script.

        Returns list of audio file paths in order.
        """
        audio_files = []

        for i, section in enumerate(script_sections):
            text = section.get("text", "")
            if not text:
                continue

            filename = f"{base_filename}_section_{i:02d}"
            audio_path = await self.generate_voice(
                text=text,
                output_filename=filename,
                provider=provider,
            )

            if audio_path:
                audio_files.append(audio_path)
            else:
                console.print(f"[yellow]Warning: Failed to generate audio for section {i}[/yellow]")

        return audio_files

    def list_available_voices(self, provider: VoiceProvider) -> dict:
        """List available voices for a provider."""
        return self.RECOMMENDED_VOICES.get(provider, {})


async def test_voice_generation():
    """Test voice generation."""
    generator = VoiceGenerator()

    console.print(f"[bold]Available providers:[/bold] {[p.value for p in generator.available_providers]}")

    best = generator.get_best_provider()
    if best:
        console.print(f"[bold]Best provider:[/bold] {best.value}")

        # Test generation
        test_text = "Hey guys, I have to show you this amazing product I just found on TikTok Shop!"
        result = await generator.generate_voice(
            text=test_text,
            output_filename="test_voice",
            provider=best,
        )

        if result:
            console.print(f"[green]Test audio saved to: {result}[/green]")
    else:
        console.print("[red]No voice providers available![/red]")


if __name__ == "__main__":
    asyncio.run(test_voice_generation())
