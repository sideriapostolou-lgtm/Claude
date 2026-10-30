"""No gamification (docs/EXPERIENCE.md §8.4, §11 ``test_experience_texts``).

Every template is rendered with extreme and null values and linted (word boundaries, any case); "Skill shown" appears
only with the label ``skilled``; chip words match the card kind; no win rate anywhere.
"""

from __future__ import annotations

import ast
import itertools
import math
import re
from pathlib import Path

import pytest

import nightcrawler.experience
from nightcrawler.experience import cards, texts
from nightcrawler.experience.constants import CHIP_WORDS, KIND_LABELS, KNOWN_PATTERNS, MEMBER_KIND, MEMBERS

EXTREMES = (None, 0, -0.0, 1, -1, 0.5, -0.5, 1e-12, 1e12, -1e12, math.nan, math.inf, -math.inf, 7, "x", True)
EXPERIENCE = Path(nightcrawler.experience.__file__).parent
_NOT_RENDERED = re.compile(r"\b(?:None|nan|inf|NaN|Infinity)\b|\{|\}")


def check(text: str) -> None:
    assert isinstance(text, str) and texts.lint(text) == [], (text, texts.lint(text))
    assert not _NOT_RENDERED.search(text), text


def test_the_lint_uses_word_boundaries_and_ignores_case() -> None:
    for bad in ("an Expert team", "PRO trader", "level up", "edge found", "Win rate 80%", "profitable",
                "money added", "it Beats chance", "we learned", "improving fast", "stop level", "XP points"):
        assert texts.lint(bad), bad
    for fine in ("protects the money", "knowledge", "levels", "pledge", "profits", "probe", "ranked", "proof",
                 "the stop price"):
        assert texts.lint(fine) == [], fine


@pytest.mark.parametrize("name", sorted(texts.TEMPLATES))
def test_every_template_renders_cleanly_with_extreme_and_null_values(name: str) -> None:
    check(texts.TEMPLATES[name].replace("{", "").replace("}", ""))  # the raw words, too
    for value in EXTREMES:
        check(texts.say(name, **{f: value for f in texts.fields(name)}))
    for combo in itertools.islice(itertools.product(EXTREMES, repeat=len(texts.fields(name))), 200):
        check(texts.say(name, **dict(zip(texts.fields(name), combo, strict=True))))


def test_every_text_function_renders_cleanly() -> None:
    labels = {m: lab for m, _, kind in MEMBERS for lab in KIND_LABELS[kind][:1]}
    for value in EXTREMES:
        for line in texts.headline_lines(graded=value, days=value, practised=value, practised_days=value,
                                         labels=labels):
            check(line)
        check(texts.loss_types_line([{"type": t, "n": value, "expected": value} for t in texts.LOSS_NAMES]))
        for primary in (*texts.LOSS_NAMES, "unknown"):
            check(texts.pm_note(primary=primary, x=value, base_rate=value, drop=value, minutes_after_entry=value,
                                gap=value, faults=["replay_disagrees"], flag="A sell burst",
                                flag_minutes_before=value))
    check(texts.loss_types_line([]))
    check(texts.bars_line({}))
    for state in (None, "cash", *texts.COACH_MONEY_STATES):
        check(texts.money_line(state))
    for text in KNOWN_PATTERNS.values():
        check(text)


def test_skill_shown_only_with_the_skilled_label() -> None:
    for (member, _, kind), alpha in itertools.product(MEMBERS, (0.01, 0.0033, 0.0001)):
        for label in KIND_LABELS[kind]:
            for paper in (True, False):
                words = texts.label_text(member, label, alpha=alpha, paper=paper) + texts.chip_word(member, label,
                                                                                                   paper=paper)
                check(words)
                assert ("skill shown" in words.lower()) == (label == "skilled"), (member, label)
    others = {k: v for k, v in texts.TEMPLATES.items() if k != "label_skilled"}
    assert not any("skill shown" in v.lower() for v in others.values())


def test_chip_words_match_the_card_kind() -> None:
    for member, _, kind in MEMBERS:
        for label in KIND_LABELS[kind]:
            word = texts.chip_word(member, label)
            assert word in CHIP_WORDS[kind].values() or (member, label) in {
                ("risk", "meets_bar"), ("risk", "below_bar"), ("broker", "not_measured")}
        for other in {lab for k, labs in KIND_LABELS.items() if k != kind for lab in labs} - set(KIND_LABELS[kind]):
            with pytest.raises(ValueError):
                texts.chip_word(member, other)
    assert texts.chip_word("risk", "meets_bar") == "Within tolerance"
    assert texts.chip_word("risk", "below_bar") == "Over tolerance"
    assert texts.chip_word("broker", "not_measured") == "Not measured on paper"
    assert texts.chip_word("broker", "not_measured", paper=False) == "Not measured"
    assert MEMBER_KIND["coach"] == "self_check" and texts.chip_word("coach", "checks_pass") == "Checks pass"


def test_green_only_for_skill_or_bar_and_never_amber() -> None:
    tones = {label: texts.chip_tone(label) for labels in KIND_LABELS.values() for label in labels}
    assert {label for label, tone in tones.items() if tone == "green"} == {"skilled", "meets_bar"}
    assert {label for label, tone in tones.items() if tone == "red"} == {"worse", "below_bar", "check_failed"}
    assert set(tones.values()) == {"green", "red", "grey"}


def test_the_money_line_changes_only_with_the_coach_state() -> None:
    assert texts.money_line(None) == texts.money_line("practice") == "Making money: not shown yet — holding cash."
    assert len({texts.money_line(s) for s in texts.COACH_MONEY_STATES}) == 3
    assert texts.CAVEAT == "Avoiding losses is not the same as making money."


def test_no_win_rate_anywhere() -> None:
    for path in sorted(EXPERIENCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} \
            | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} \
            | {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and n.value.isidentifier()}
        assert not {n for n in names if re.search(r"win_?rate|hit_?rate|winners?_pct", n, re.IGNORECASE)}, path.name
    state = repr(cards.empty_state())
    assert "win" not in state.lower().replace("window", "")
