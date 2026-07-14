"""Highlight segmentation: score transcript windows and pick clip-worthy spans.

Deterministic, offline heuristic — no API calls. Signals:

- hook phrases (questions, "the secret", "here's why", numbers, superlatives)
- direct address ("you", "your") and emotional markers
- speech density (words/sec) relative to the video average
- natural boundaries: clips start after pauses and end before them
- optional chapter titles parsed from the video description
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .timecode import parse_timecode
from .transcript import Cue

_HOOK_PATTERNS = [
    (re.compile(r"\?"), 1.5, "question"),
    (re.compile(r"\!"), 1.0, "exclamation"),
    (re.compile(r"\b(secret|trick|hack|mistake|warning|never|always|nobody|everyone)\b", re.I), 2.0, "hook word"),
    (re.compile(r"\b(best|worst|biggest|craziest|insane|amazing|incredible|unbelievable)\b", re.I), 1.5, "superlative"),
    (re.compile(r"\b(here'?s (why|how|what)|the (real|only) (reason|way)|what (most|no one))\b", re.I), 2.5, "hook phrase"),
    (re.compile(r"\b(you|your)\b", re.I), 0.3, "direct address"),
    (re.compile(r"\b\d+(\.\d+)?%?\b"), 0.8, "number"),
    (re.compile(r"\b(but|however|actually|turns out|the problem is)\b", re.I), 0.7, "turn"),
]

_CHAPTER_LINE_RE = re.compile(
    r"^\s*[-*•]?\s*\(?((?:\d{1,2}:)?\d{1,2}:\d{2})\)?\s*[-–—:.]?\s*(\S.*)$"
)


@dataclass(frozen=True)
class Clip:
    start: float
    end: float
    score: float
    reasons: tuple[str, ...] = ()
    preview: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Chapter:
    start: float
    title: str


def parse_chapters(description: str) -> list[Chapter]:
    """Extract "0:00 Intro"-style chapter markers from a video description.

    YouTube only honors chapter lists that start at 0:00 with 3+ entries in
    ascending order; we apply the same rule.
    """
    chapters: list[Chapter] = []
    for line in description.splitlines():
        m = _CHAPTER_LINE_RE.match(line)
        if not m:
            continue
        try:
            start = parse_timecode(m.group(1))
        except ValueError:
            continue
        title = m.group(2).strip()
        if title:
            chapters.append(Chapter(start, title))
    if len(chapters) < 3 or chapters[0].start != 0:
        return []
    if any(b.start <= a.start for a, b in zip(chapters, chapters[1:])):
        return []
    return chapters


def _score_text(text: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    for pattern, weight, label in _HOOK_PATTERNS:
        hits = len(pattern.findall(text))
        if hits:
            score += weight * min(hits, 3)  # cap so one signal can't dominate
            reasons.append(label)
    return score, reasons


def suggest_clips(
    cues: list[Cue],
    *,
    count: int = 5,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
    pause_gap: float = 1.5,
) -> list[Clip]:
    """Return up to `count` non-overlapping highlight clips, best first."""
    if not cues:
        return []
    cues = sorted(cues, key=lambda c: c.start)

    total_words = sum(c.words for c in cues)
    total_time = max(cues[-1].end - cues[0].start, 1e-9)
    avg_density = total_words / total_time

    # Split the transcript into passages at natural pauses.
    passages: list[list[Cue]] = [[cues[0]]]
    for prev, cur in zip(cues, cues[1:]):
        if cur.start - prev.end >= pause_gap:
            passages.append([cur])
        else:
            passages[-1].append(cur)

    candidates: list[Clip] = []
    for passage in passages:
        # Slide a window of cues within each passage.
        n = len(passage)
        i = 0
        while i < n:
            j = i
            while j < n and passage[j].end - passage[i].start <= max_duration:
                j += 1
            window = passage[i:max(j, i + 1)]
            start, end = window[0].start, window[-1].end
            duration = end - start
            if duration >= min_duration:
                text = " ".join(c.text for c in window)
                score, reasons = _score_text(text)
                words = sum(c.words for c in window)
                density = words / max(duration, 1e-9)
                if avg_density > 0:
                    score *= min(density / avg_density, 1.5)
                score /= max(duration / max_duration, 0.25)  # prefer tighter clips
                candidates.append(
                    Clip(
                        start=start,
                        end=end,
                        score=round(score, 3),
                        reasons=tuple(dict.fromkeys(reasons)),
                        preview=text[:160],
                    )
                )
            # Advance roughly half a window for overlap coverage.
            i += max((j - i) // 2, 1)

    # Greedy non-overlapping selection, best score first.
    candidates.sort(key=lambda c: c.score, reverse=True)
    chosen: list[Clip] = []
    for cand in candidates:
        if len(chosen) >= count:
            break
        if all(cand.end <= c.start or cand.start >= c.end for c in chosen):
            chosen.append(cand)
    chosen.sort(key=lambda c: c.start)
    return chosen
