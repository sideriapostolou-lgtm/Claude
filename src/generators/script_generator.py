"""
UGC Script Generator for viral TikTok content.

Creates compelling scripts optimized for engagement and conversions.
"""

import json
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import os
from rich.console import Console
from rich.panel import Panel

console = Console()


class VideoFormat(Enum):
    """Video format types for UGC content."""
    PROBLEM_SOLUTION = "problem_solution"
    UNBOXING = "unboxing"
    BEFORE_AFTER = "before_after"
    REVIEW = "review"
    TUTORIAL = "tutorial"
    DAY_IN_LIFE = "day_in_life"
    COMPARISON = "comparison"
    STORY_TIME = "story_time"
    GET_READY = "get_ready"
    HAUL = "haul"


class HookType(Enum):
    """Types of attention-grabbing hooks."""
    PROBLEM = "problem"  # "Are you tired of..."
    CURIOSITY = "curiosity"  # "Wait until you see this..."
    SHOCK = "shock"  # "I can't believe this actually works"
    SOCIAL_PROOF = "social_proof"  # "Everyone's been asking about..."
    DIRECT = "direct"  # "You NEED this..."
    QUESTION = "question"  # "Have you ever..."
    TRANSFORMATION = "transformation"  # "This changed my life..."
    CHALLENGE = "challenge"  # "I tested this viral product..."


@dataclass
class ScriptSection:
    """A section of the UGC script."""
    name: str
    duration: float  # seconds
    text: str
    visual_notes: str = ""
    audio_notes: str = ""


@dataclass
class UGCScript:
    """Complete UGC video script."""
    title: str
    product_name: str
    format: VideoFormat
    hook_type: HookType
    total_duration: float
    sections: list[ScriptSection] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    sound_suggestion: str = ""
    cta: str = ""
    caption: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "product_name": self.product_name,
            "format": self.format.value,
            "hook_type": self.hook_type.value,
            "total_duration": self.total_duration,
            "sections": [
                {
                    "name": s.name,
                    "duration": s.duration,
                    "text": s.text,
                    "visual_notes": s.visual_notes,
                    "audio_notes": s.audio_notes,
                }
                for s in self.sections
            ],
            "hashtags": self.hashtags,
            "sound_suggestion": self.sound_suggestion,
            "cta": self.cta,
            "caption": self.caption,
        }


class UGCScriptGenerator:
    """
    Generates viral UGC scripts for TikTok Shop products.

    Script Structure for Maximum Engagement:
    1. HOOK (0-3s): Grab attention immediately
    2. PROBLEM (3-8s): Relate to viewer's pain point
    3. SOLUTION (8-15s): Introduce product as solution
    4. DEMO (15-35s): Show product in action
    5. RESULTS (35-45s): Show transformation/benefits
    6. CTA (45-60s): Call to action

    Key principles:
    - Hook in first 1-3 seconds (prevent scroll)
    - Text overlay for accessibility
    - Native, authentic feel
    - Clear value proposition
    - Strong CTA with urgency
    """

    # Proven hook templates
    HOOK_TEMPLATES = {
        HookType.PROBLEM: [
            "Okay but why did no one tell me about this sooner?",
            "I was today years old when I found out about this...",
            "Stop scrolling if you struggle with {problem}",
            "POV: You finally found the solution to {problem}",
            "If you're still dealing with {problem}, watch this",
        ],
        HookType.CURIOSITY: [
            "Wait for it... this is insane",
            "I have to show you what just arrived",
            "Okay TikTok made me buy this and...",
            "This might be the best purchase I've ever made",
            "You're not gonna believe what this does",
        ],
        HookType.SHOCK: [
            "I literally gasped when I tried this",
            "The way my jaw DROPPED",
            "I've never seen anything work this fast",
            "This should be illegal it works so well",
            "I wasn't expecting it to actually work but...",
        ],
        HookType.SOCIAL_PROOF: [
            "Everyone keeps asking about this",
            "This is why it has 10,000+ 5-star reviews",
            "TikTok made me buy it and I get it now",
            "Okay I finally tried the viral {product}",
            "This is THE product everyone's talking about",
        ],
        HookType.DIRECT: [
            "You need this immediately",
            "Run don't walk to get this",
            "Adding this to cart for you right now",
            "This is your sign to finally get it",
            "Trust me, you need this in your life",
        ],
        HookType.QUESTION: [
            "Have you ever wished there was an easier way to {task}?",
            "Why is no one talking about this?",
            "Am I the only one who didn't know about this?",
            "Have you tried the {product} everyone's obsessed with?",
            "What if I told you {benefit} was this easy?",
        ],
        HookType.TRANSFORMATION: [
            "Watch this transformation",
            "Before and after using {product} for one week",
            "This completely changed my {routine}",
            "From this to THIS in just {timeframe}",
            "The difference is INSANE",
        ],
        HookType.CHALLENGE: [
            "I tested the viral {product} so you don't have to",
            "Putting this to the test - does it actually work?",
            "Is this worth the hype? Let's find out",
            "I tried {product} for 7 days, here's what happened",
            "Testing TikTok's favorite product",
        ],
    }

    # CTA templates
    CTA_TEMPLATES = [
        "Link in bio! Use code {code} for {discount}% off",
        "Click the link before it sells out again",
        "TikTok Shop link in my bio - trust me on this one",
        "Get yours from the TikTok Shop below ⬇️",
        "Comment '{keyword}' and I'll send you the link!",
        "Link in bio! They always sell out fast",
        "Grab it while it's still in stock - link in bio",
        "This is your sign - TikTok Shop link below",
    ]

    # Problem-solution pairs by category
    PROBLEM_SOLUTIONS = {
        "beauty": {
            "problems": [
                "dry skin that nothing seems to fix",
                "makeup that never stays on",
                "skincare routine that takes forever",
                "acne that won't go away",
                "dull, tired-looking skin",
            ],
            "solutions": [
                "hydrated, glowing skin",
                "all-day flawless coverage",
                "a simple 3-step routine",
                "clear, confident skin",
                "radiant, youthful glow",
            ],
        },
        "home": {
            "problems": [
                "messy, cluttered spaces",
                "cleaning that takes hours",
                "organization that never lasts",
                "stubborn stains and messes",
                "limited storage space",
            ],
            "solutions": [
                "a perfectly organized home",
                "cleaning in half the time",
                "storage that actually works",
                "spotless surfaces instantly",
                "maximized space efficiency",
            ],
        },
        "tech": {
            "problems": [
                "phone dying at the worst times",
                "tangled cables everywhere",
                "slow, frustrating devices",
                "poor quality photos/videos",
                "uncomfortable tech accessories",
            ],
            "solutions": [
                "all-day battery life",
                "clean, organized setup",
                "lightning-fast performance",
                "professional-quality content",
                "comfort meets functionality",
            ],
        },
        "kitchen": {
            "problems": [
                "cooking that takes forever",
                "meal prep overwhelm",
                "food going bad too quickly",
                "difficult cleanup",
                "boring, repetitive meals",
            ],
            "solutions": [
                "quick, easy meals",
                "stress-free meal prep",
                "longer-lasting freshness",
                "effortless cleanup",
                "exciting new recipes",
            ],
        },
        "fitness": {
            "problems": [
                "no time for the gym",
                "equipment that's uncomfortable",
                "lack of motivation",
                "plateaued progress",
                "expensive gym memberships",
            ],
            "solutions": [
                "effective home workouts",
                "comfortable, functional gear",
                "motivation on demand",
                "break through plateaus",
                "gym-quality results at home",
            ],
        },
    }

    def __init__(self, use_ai: bool = True):
        """Initialize the script generator."""
        self.use_ai = use_ai
        self.openai_client = None
        self.anthropic_client = None

        if use_ai:
            self._init_ai_clients()

    def _init_ai_clients(self):
        """Initialize AI clients for enhanced script generation."""
        try:
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=openai_key)
        except ImportError:
            pass

        try:
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")
            if anthropic_key:
                from anthropic import Anthropic
                self.anthropic_client = Anthropic(api_key=anthropic_key)
        except ImportError:
            pass

    def generate_script(
        self,
        product_name: str,
        category: str,
        key_benefits: list[str],
        target_audience: str = "general",
        video_format: VideoFormat = VideoFormat.PROBLEM_SOLUTION,
        duration: int = 30,
        hook_type: Optional[HookType] = None,
        discount_code: Optional[str] = None,
    ) -> UGCScript:
        """
        Generate a complete UGC script for a product.

        Args:
            product_name: Name of the product
            category: Product category (beauty, home, tech, etc.)
            key_benefits: List of main product benefits
            target_audience: Target demographic
            video_format: Type of video format to use
            duration: Target video duration in seconds
            hook_type: Type of hook to use (random if not specified)
            discount_code: Optional discount code to include
        """
        console.print(f"[cyan]📝 Generating script for {product_name}...[/cyan]")

        # Select hook type if not specified
        if not hook_type:
            import random
            hook_type = random.choice(list(HookType))

        # Get category-specific content
        cat_content = self.PROBLEM_SOLUTIONS.get(
            category.lower(),
            self.PROBLEM_SOLUTIONS["home"]  # Default fallback
        )

        # Generate sections based on format
        if video_format == VideoFormat.PROBLEM_SOLUTION:
            script = self._generate_problem_solution(
                product_name, category, key_benefits, cat_content, hook_type, duration
            )
        elif video_format == VideoFormat.UNBOXING:
            script = self._generate_unboxing(
                product_name, category, key_benefits, hook_type, duration
            )
        elif video_format == VideoFormat.REVIEW:
            script = self._generate_review(
                product_name, category, key_benefits, hook_type, duration
            )
        elif video_format == VideoFormat.BEFORE_AFTER:
            script = self._generate_before_after(
                product_name, category, key_benefits, cat_content, hook_type, duration
            )
        else:
            # Default to problem-solution
            script = self._generate_problem_solution(
                product_name, category, key_benefits, cat_content, hook_type, duration
            )

        # Add CTA
        cta_template = self.CTA_TEMPLATES[0]
        if discount_code:
            script.cta = cta_template.format(code=discount_code, discount=15)
        else:
            script.cta = "Link in bio! Get yours from TikTok Shop ⬇️"

        # Generate hashtags
        script.hashtags = self._generate_hashtags(product_name, category)

        # Generate caption
        script.caption = self._generate_caption(script)

        return script

    def _generate_problem_solution(
        self,
        product_name: str,
        category: str,
        benefits: list[str],
        cat_content: dict,
        hook_type: HookType,
        duration: int
    ) -> UGCScript:
        """Generate problem-solution format script."""
        import random

        problem = random.choice(cat_content["problems"])
        solution = random.choice(cat_content["solutions"])

        # Get hook
        hook_templates = self.HOOK_TEMPLATES[hook_type]
        hook = random.choice(hook_templates).format(
            problem=problem,
            product=product_name,
            benefit=benefits[0] if benefits else solution,
            task=problem,
        )

        sections = [
            ScriptSection(
                name="Hook",
                duration=3,
                text=hook,
                visual_notes="Close-up on face with surprised/excited expression, or product tease",
                audio_notes="Trending sound or original audio with energy",
            ),
            ScriptSection(
                name="Problem",
                duration=5,
                text=f"So I've been dealing with {problem} for the longest time, and nothing worked...",
                visual_notes="B-roll of the problem or talking to camera",
                audio_notes="Relatable, conversational tone",
            ),
            ScriptSection(
                name="Discovery",
                duration=4,
                text=f"Until I found this {product_name} on TikTok Shop",
                visual_notes="Show product packaging or holding product",
                audio_notes="Build excitement",
            ),
            ScriptSection(
                name="Demo",
                duration=duration - 20,
                text=f"Watch this... *demonstrates product* {benefits[0] if benefits else 'and look at that!'}",
                visual_notes="Clear demonstration of product in use, show results",
                audio_notes="Focus on visuals, minimal talking",
            ),
            ScriptSection(
                name="Results",
                duration=5,
                text=f"Now I have {solution}! This is literally a game changer.",
                visual_notes="Show end result, before/after if applicable",
                audio_notes="Genuine excitement",
            ),
            ScriptSection(
                name="CTA",
                duration=3,
                text="Link in bio if you need this in your life!",
                visual_notes="Point down or show TikTok Shop icon",
                audio_notes="Clear, direct call to action",
            ),
        ]

        return UGCScript(
            title=f"{product_name} - Problem Solution",
            product_name=product_name,
            format=VideoFormat.PROBLEM_SOLUTION,
            hook_type=hook_type,
            total_duration=duration,
            sections=sections,
            sound_suggestion="Trending sound or original voiceover",
        )

    def _generate_unboxing(
        self,
        product_name: str,
        category: str,
        benefits: list[str],
        hook_type: HookType,
        duration: int
    ) -> UGCScript:
        """Generate unboxing format script."""
        import random

        hook = random.choice(self.HOOK_TEMPLATES[HookType.CURIOSITY]).format(
            product=product_name
        )

        sections = [
            ScriptSection(
                name="Hook",
                duration=3,
                text=hook,
                visual_notes="Package in frame, hands ready to open",
                audio_notes="Build anticipation with trending sound",
            ),
            ScriptSection(
                name="Unbox",
                duration=8,
                text="Okay let's see what's inside... *opens package*",
                visual_notes="ASMR-style unboxing, close-up shots",
                audio_notes="Satisfying opening sounds, minimal talking",
            ),
            ScriptSection(
                name="First Impression",
                duration=5,
                text=f"Oh wow, okay this is {benefits[0] if benefits else 'really nice'}",
                visual_notes="Hold up product, show from multiple angles",
                audio_notes="Genuine reaction",
            ),
            ScriptSection(
                name="Quick Demo",
                duration=duration - 22,
                text=f"Let me try this right now... *uses product*",
                visual_notes="First-use demonstration",
                audio_notes="Real-time reactions",
            ),
            ScriptSection(
                name="Verdict",
                duration=4,
                text=f"Okay I'm obsessed. This is definitely worth it.",
                visual_notes="Show final result or product",
                audio_notes="Conclusive, positive tone",
            ),
            ScriptSection(
                name="CTA",
                duration=2,
                text="TikTok Shop link below!",
                visual_notes="Point to link",
                audio_notes="Quick, direct",
            ),
        ]

        return UGCScript(
            title=f"{product_name} - Unboxing",
            product_name=product_name,
            format=VideoFormat.UNBOXING,
            hook_type=hook_type,
            total_duration=duration,
            sections=sections,
            sound_suggestion="ASMR/satisfying sound or original",
        )

    def _generate_review(
        self,
        product_name: str,
        category: str,
        benefits: list[str],
        hook_type: HookType,
        duration: int
    ) -> UGCScript:
        """Generate honest review format script."""
        import random

        hook = random.choice(self.HOOK_TEMPLATES[HookType.CHALLENGE]).format(
            product=product_name
        )

        sections = [
            ScriptSection(
                name="Hook",
                duration=3,
                text=hook,
                visual_notes="Talking head or holding product",
                audio_notes="Honest, conversational tone",
            ),
            ScriptSection(
                name="Background",
                duration=5,
                text=f"So I got this {product_name} from TikTok Shop and I've been using it for a week now",
                visual_notes="Show product, lifestyle shots",
                audio_notes="Set the scene",
            ),
            ScriptSection(
                name="Pros",
                duration=duration - 20,
                text=f"What I love: {', '.join(benefits[:3]) if benefits else 'it actually works'}",
                visual_notes="Demonstrate each pro visually",
                audio_notes="Enthusiastic but authentic",
            ),
            ScriptSection(
                name="Cons/Honesty",
                duration=5,
                text="The only thing is... [minor con]. But honestly it's not a dealbreaker.",
                visual_notes="Address minor imperfection",
                audio_notes="Keep it balanced and real",
            ),
            ScriptSection(
                name="Verdict",
                duration=4,
                text="Overall? 9/10, would definitely recommend.",
                visual_notes="Final product shot",
                audio_notes="Conclusive recommendation",
            ),
            ScriptSection(
                name="CTA",
                duration=3,
                text="Link in my TikTok Shop!",
                visual_notes="Show product one more time",
                audio_notes="Clear CTA",
            ),
        ]

        return UGCScript(
            title=f"{product_name} - Honest Review",
            product_name=product_name,
            format=VideoFormat.REVIEW,
            hook_type=hook_type,
            total_duration=duration,
            sections=sections,
            sound_suggestion="Chill background music or original voiceover",
        )

    def _generate_before_after(
        self,
        product_name: str,
        category: str,
        benefits: list[str],
        cat_content: dict,
        hook_type: HookType,
        duration: int
    ) -> UGCScript:
        """Generate before/after transformation script."""
        import random

        problem = random.choice(cat_content["problems"])
        solution = random.choice(cat_content["solutions"])

        sections = [
            ScriptSection(
                name="Hook",
                duration=2,
                text="Watch this transformation",
                visual_notes="Split screen tease or 'before' state",
                audio_notes="Trending transformation sound",
            ),
            ScriptSection(
                name="Before",
                duration=5,
                text=f"This was me before - dealing with {problem}",
                visual_notes="Show 'before' state clearly",
                audio_notes="Set the problem",
            ),
            ScriptSection(
                name="Product Intro",
                duration=3,
                text=f"Then I started using {product_name}...",
                visual_notes="Show product",
                audio_notes="Transition building",
            ),
            ScriptSection(
                name="Process",
                duration=duration - 20,
                text="*Montage of using product*",
                visual_notes="Time-lapse or montage of product use",
                audio_notes="Trending sound builds",
            ),
            ScriptSection(
                name="After Reveal",
                duration=7,
                text=f"And now... {solution}!",
                visual_notes="Dramatic reveal of 'after' state",
                audio_notes="Sound drop/peak moment",
            ),
            ScriptSection(
                name="CTA",
                duration=3,
                text="Link below to get the same results!",
                visual_notes="Side-by-side before/after",
                audio_notes="Encourage action",
            ),
        ]

        return UGCScript(
            title=f"{product_name} - Transformation",
            product_name=product_name,
            format=VideoFormat.BEFORE_AFTER,
            hook_type=HookType.TRANSFORMATION,
            total_duration=duration,
            sections=sections,
            sound_suggestion="Trending transformation/reveal sound",
        )

    def _generate_hashtags(self, product_name: str, category: str) -> list[str]:
        """Generate optimal hashtag set."""
        base_tags = ["fyp", "tiktokshop", "tiktokmademebuyit"]

        category_tags = {
            "beauty": ["beautytok", "skincare", "makeupfinds"],
            "home": ["hometok", "organization", "homefinds"],
            "tech": ["techtok", "gadgets", "techfinds"],
            "kitchen": ["kitchentok", "cooking", "kitchenfinds"],
            "fitness": ["fitnesstok", "workout", "fitnessfinds"],
        }

        tags = base_tags + category_tags.get(category.lower(), ["viral", "trending"])
        return tags[:6]  # TikTok optimal is 4-6 hashtags

    def _generate_caption(self, script: UGCScript) -> str:
        """Generate video caption."""
        hashtags = " ".join([f"#{tag}" for tag in script.hashtags])
        return f"{script.sections[0].text[:100]}... {script.cta}\n\n{hashtags}"

    def generate_with_ai(
        self,
        product_name: str,
        category: str,
        key_benefits: list[str],
        target_audience: str,
        video_format: VideoFormat,
        duration: int,
    ) -> Optional[UGCScript]:
        """Use AI to generate a more creative, customized script."""
        if not self.openai_client and not self.anthropic_client:
            console.print("[yellow]No AI client available, using template generation[/yellow]")
            return None

        prompt = f"""Create a viral TikTok UGC script for this product:

Product: {product_name}
Category: {category}
Key Benefits: {', '.join(key_benefits)}
Target Audience: {target_audience}
Video Format: {video_format.value}
Duration: {duration} seconds

Requirements:
1. Hook must grab attention in first 2-3 seconds
2. Must feel authentic and native to TikTok
3. Include visual and audio notes for each section
4. End with clear call-to-action
5. Use relatable language for {target_audience}

Return a JSON object with this structure:
{{
    "title": "...",
    "sections": [
        {{"name": "...", "duration": X, "text": "...", "visual_notes": "...", "audio_notes": "..."}}
    ],
    "sound_suggestion": "...",
    "cta": "..."
}}"""

        try:
            if self.openai_client:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8,
                )
                content = response.choices[0].message.content
            elif self.anthropic_client:
                response = self.anthropic_client.messages.create(
                    model="claude-3-sonnet-20240229",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.content[0].text

            # Parse JSON from response
            data = json.loads(content)

            sections = [
                ScriptSection(
                    name=s["name"],
                    duration=s["duration"],
                    text=s["text"],
                    visual_notes=s.get("visual_notes", ""),
                    audio_notes=s.get("audio_notes", ""),
                )
                for s in data["sections"]
            ]

            return UGCScript(
                title=data["title"],
                product_name=product_name,
                format=video_format,
                hook_type=HookType.CURIOSITY,
                total_duration=duration,
                sections=sections,
                sound_suggestion=data.get("sound_suggestion", ""),
                cta=data.get("cta", ""),
            )

        except Exception as e:
            console.print(f"[yellow]AI generation failed: {e}. Using template.[/yellow]")
            return None

    def display_script(self, script: UGCScript):
        """Display formatted script."""
        console.print(Panel(
            f"[bold]{script.title}[/bold]\n"
            f"Format: {script.format.value} | Duration: {script.total_duration}s\n"
            f"Hook Type: {script.hook_type.value}",
            title="📝 UGC Script",
            border_style="cyan",
        ))

        for i, section in enumerate(script.sections, 1):
            console.print(f"\n[bold cyan]Section {i}: {section.name}[/bold cyan] ({section.duration}s)")
            console.print(f"[white]Script:[/white] \"{section.text}\"")
            if section.visual_notes:
                console.print(f"[dim]📹 Visual: {section.visual_notes}[/dim]")
            if section.audio_notes:
                console.print(f"[dim]🎵 Audio: {section.audio_notes}[/dim]")

        console.print(f"\n[green]🎯 CTA:[/green] {script.cta}")
        console.print(f"[blue]🎵 Sound:[/blue] {script.sound_suggestion}")
        console.print(f"[magenta]#️⃣ Hashtags:[/magenta] {' '.join(['#' + t for t in script.hashtags])}")

        console.print("\n[bold]📱 Caption:[/bold]")
        console.print(f"[dim]{script.caption}[/dim]")
