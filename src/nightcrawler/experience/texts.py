"""Every owner-facing string of experience (docs/EXPERIENCE.md §8), and the no-gamification lint.

Strings come only from the fixed templates in :data:`TEMPLATES`, filled by :func:`say`, which formats every value
itself by the field's SUFFIX, so a template can be rendered with any value - None, NaN and infinities give "?":

==========  =====================================  ==========  ============================================
suffix      value -> text                          suffix      value -> text
==========  =====================================  ==========  ============================================
``_pp``     points, ``+1.2``                       ``_pct``    a share as a percent, ``31``
``_x``      a ratio, ``1.4``                       ``_10``     a share as "k" of 10, ``3``
``_s``      seconds, ``12``                        ``_k``      a share as "1 in k", ``6``
``_usd``    dollars, ``0.25``                      ``days``    ``1 day`` / ``14 days``
``n``/``_n`` a count, ``4,212``                    ``_txt``    a string (printable, at most 120 chars)
==========  =====================================  ==========  ============================================

``tests/test_experience_texts.py`` renders every template with extreme and null values and fails on any
word-boundary, case-insensitive match of :data:`BANNED` (:func:`lint`).

* No experience points, badges, ranks, streaks or win rates: experience is shown as counts, bands and labels.
* "Skill shown" appears only in :func:`label_text` for the label ``skilled`` (and as that label's chip word).
* Chip words depend on the card kind (:func:`chip_word`); colour (:func:`chip_tone`) is never the only signal.
* Post-mortem notes say "stop price", never "stop level".
"""

from __future__ import annotations

import math
import re
import string
from collections.abc import Mapping, Sequence
from typing import Any

from nightcrawler.experience.constants import (
    CHIP_WORDS,
    GREEN_LABELS,
    KIND_LABELS,
    MEMBER_KIND,
    MEMBER_NAMES,
    RED_LABELS,
    RISK_CHIP_WORDS,
    SKILLS_MEASURABLE,
)
from nightcrawler.experience.stats import check_pct

__all__ = [
    "BANNED", "SKILL_SHOWN", "CAVEAT", "TEMPLATES", "LOSS_NAMES", "PRACTICE_WINDOWS", "COACH_MONEY_STATES",
    "TEXT_MAX", "lint", "fields", "say", "chip_word", "chip_tone", "label_text", "headline_lines", "bars_line",
    "money_line", "independent_line", "loss_types_line", "pm_note",
]

#: Never in an owner-facing string (word boundaries, any case).
BANNED = ("expert", "pro", "master", "level", "XP", "rank", "elite", "guaranteed", "smart money", "win rate",
          "winning streak", "profitable", "profit", "studied", "experienced", "edge", "learned", "money added",
          "proven", "beats", "improving", "improved", "stop level")
_BANNED_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in BANNED) + r")\b", re.IGNORECASE)
SKILL_SHOWN = "Skill shown"
CAVEAT = "Avoiding losses is not the same as making money."
TEXT_MAX = 120
PRACTICE_WINDOWS = {"first_3h": "first 3 hours after graduation only", "bot_window": "in the bot's own window"}
COACH_MONEY_STATES = ("paper_champion", "live_ready", "live")
LOSS_NAMES = {"pipeline_fault": "pipeline fault", "rug_missed": "rug missed", "regime": "bad market",
              "oversize": "too large for the money", "late_entry": "late entry", "bad_entry": "bad entry",
              "early_exit": "early exit", "late_exit": "late exit", "cost_eaten": "costs ate the gain",
              "missed_winner": "missed winner", "variance": "no clear cause"}

TEMPLATES: dict[str, str] = {
    # ---- the team headline (§8.2)
    "practice": "Practice record: {graded_n} new coins graded over {days}; {practised_txt}.",
    "practised": "{n} past coins practised ({window_txt})",
    "practised_days": "{days}, {window_txt}",
    "practised_none": "no past coins practised yet",
    "skills": "Skills shown ({check_txt}% check): {k_n} of {of_n}.",
    "collecting": "Still collecting: {n} ({names_txt})",
    "jev_off": "Jev is off",
    "member_off": "{name_txt} not measured",
    "bars": "Bars: Crawler {crawler_txt} · Broker {broker_txt} · Risk {risk_txt}.",
    "money_none": "Making money: not shown yet — holding cash.",
    "money_paper_champion": "Making money: one strategy has shown it on paper; real money still needs real quotes "
                            "and your OK.",
    "money_live_ready": "Making money: shown on paper and on real quotes; real money only with your OK.",
    "money_live": "Making money: shown on paper and on real quotes; real money is trading.",
    "graded": "Graded on {n} coins · {days}",
    "graded_trades": "Graded on {n} trades · {days}",
    # ---- labels (§5.1)
    "label_not_measured": "Not measured yet.",
    "label_judge_off": "Jev is off.",
    "label_broker_paper": "Real-money slippage cannot be measured on paper.",
    "label_not_enough": "Still collecting.",
    "label_no_skill_yet": "No skill yet ({check_txt}% check).",
    "label_skilled": SKILL_SHOWN + " ({check_txt}% check): the whole range is above what chance gives.",
    "label_worse": "Worse than chance ({check_txt}% check): the whole range is below what chance gives.",
    "label_meets_bar": "Meets the bar.",
    "label_below_bar": "Below the bar.",
    "label_within_tolerance": "Within tolerance.",
    "label_over_tolerance": "Over tolerance.",
    "label_not_built": "Not built yet.",
    "label_checks_pass": "Checks pass.",
    "label_check_failed": "Check failed.",
    "checks_failed": "Failed: {names_txt}.",
    # ---- card plain words (§5.2)
    "cocoon": "Cocoon checked {n} coins on {days}. It blocks rugs {lift_x}× as often as a coin flip blocking the "
              "same share ({rc_10} vs {block_10} of 10). It wrongly blocks 1 in {fb_k} good coins. After its blocks, "
              "a random trade in the bot's window changed by {vv_pp} points [{lo_pp}, {hi_pp}]{still_lose_txt}. "
              "{label_txt}",
    "still_lose": " — trades still lose on average",
    "strategy": "Strategy has been graded on {n} trades on {coins_n} coins over {days}. Compared with buying at a "
                "random moment on similar coins, its entries did {ee_pp} points [{lo_pp}, {hi_pp}] per trade. After "
                "all costs it averaged {mean_pp} points per trade. {label_txt}",
    "radar": "Radar has watched {n} trades over {days}. When it pulled us out, that saved {ds_pp} points per exit "
             "[{lo_pp}, {hi_pp}] compared with getting out at random times. It got out before the crash in "
             "{early_10} of 10 crashes. {label_txt}",
    "jev": "Jev has judged {n} trades over {days}. After its no-votes, the trades left did {vv_pp} points "
           "[{lo_pp}, {hi_pp}] per trade compared with all of them; a random no at the same rate would give 0. "
           "Cost: ${cost_usd} per point. {label_txt}",
    "crawler": "Crawler saw {recall_10} of 10 new graduates within 15 minutes of them becoming tradeable (the bar "
               "is 9).",
    "gate": "Random trades its age and size rules allow did {vv_pp} points [{lo_pp}, {hi_pp}] compared with random "
            "trades under no rules — consistent with a pattern we knew before (KP-1).",
    "broker_paper": "Broker took {p50_s} s from decision to fill (slowest 1 in 10: {p90_s} s). Real-money slippage "
                    "cannot be measured on paper.",
    "broker_live": "Broker took {p50_s} s from decision to fill (slowest 1 in 10: {p90_s} s). Fills cost {sf_pp} "
                   "points [{lo_pp}, {hi_pp}] more than the cost model per round trip; we accept at most 0.5. "
                   "{label_txt}",
    "risk": "Risk: {n} paper trades on {days}. One rug costs about {rug_pct}% of the money at today's size.",
    "coach_ok": "Coach: the random-entry control keeps losing, as it should ({pl_pp} points per trade). Situation "
                "ranges caught {cov_10} of 10 outcomes (should be 8). No forecaster yet.",
    "coach_bad": "Coach: the random-entry control is not losing as it should ({pl_pp} points per trade): the "
                 "simulator may be too kind. Situation ranges caught {cov_10} of 10 outcomes (should be 8). No "
                 "forecaster yet.",
    # ---- metric names and texts (§9 range bars)
    "m_after_blocks": "Random trade after its blocks",
    "m_rugs_blocked": "Rugs blocked",
    "m_false_blocks": "Good coins wrongly blocked",
    "m_entries": "Entries vs random entries on similar coins",
    "m_mean": "Average after all costs",
    "m_exits": "Exits vs random exit times",
    "m_stop_gap": "Stop fills vs the stop price",
    "m_saved": "Saved per exit vs random exit times",
    "m_early": "Got out before the crash",
    "m_pre_buy": "Before buying: trades left after its no",
    "m_false_alarms": "False alarms",
    "m_after_no": "Trades left after its no-votes",
    "m_no_votes": "No-votes",
    "m_cost_point": "Cost per point",
    "m_seen15": "Seen within 15 minutes",
    "m_lag": "Median lag",
    "m_gate": "Age and size rules (KP-1, not a skill)",
    "m_latency": "Decision to fill",
    "m_shortfall": "Cost beyond the model",
    "m_rug": "One rug costs",
    "m_worst_day": "Worst day",
    "m_trades": "Trades taken",
    "m_placebo": "Random-entry control",
    "m_ranges": "Situation ranges held",
    "m_forecaster": "Forecaster",
    "t_points": "{v_pp} pts [{lo_pp}, {hi_pp}]",
    "t_lift": "{lift_x}× a coin flip ({rc_10} vs {block_10} of 10)",
    "t_one_in": "1 in {share_k}",
    "t_stop_gap": "{gap_x}× the planned stop",
    "t_crashes": "{n} crashes so far",
    "t_of": "{k_n} of {n}",
    "t_usd": "${v_usd}",
    "t_recall": "{recall_10} of 10 within 15 minutes (the bar is 9)",
    "t_lags": "within 5 min: {r5_pct}%, 15 min: {r15_pct}%, 60 min: {r60_pct}%",
    "t_latency": "{p50_s} s (slowest 1 in 10: {p90_s} s)",
    "t_rugs": "{n} rugs hit so far",
    "t_trades": "{n} paper trades",
    "t_placebo": "{n} placebo trades",
    "t_outcomes": "{n} outcomes",
    "t_no_forecaster": "no forecaster yet",
    "worst_day": "Worst day: {worst_pct}% against the {limit_pct}% daily limit; {days} ended past it (the limit is "
                 "checked before entries only).",
    # ---- coverage lines
    "coverage": "Checked {checked_pct}% of graded coins; {unavailable_pct}% of checks had a source unavailable "
                "(counted as the live rule treats them).",
    "matched": "Matched {k_n} of {n} trades with random entries on similar coins.",
    "radar_exits": "{k_n} radar exits on {n} paper positions.",
    "missed_parity": "Missed coins did {v_pp} points against seen coins (random entries).",
    # ---- loss library and lessons (§6)
    "loss_types": "Loss types this week: {items_txt}.",
    "loss_types_none": "Loss types this week: none graded yet.",
    "loss_first": "{name_txt} {n} (random entries in the same situations: {e_x} expected)",
    "loss_next": "{name_txt} {n} ({e_x} expected)",
    "pm_rug": "{result_txt} {loss_pct} points: the price fell {drop_pct}% in one minute, {after_n} minutes after "
              "entry, and the fill was {gap_pct} points below the stop price. Random entries in this situation hit "
              "such a fall {rate_10} times in 10.",
    "pm_other": "{result_txt} {loss_pct} points; how it ended: {name_txt}. Random entries in this situation ended "
                "this way {rate_10} times in 10.",
    "pm_fault": "{result_txt} {loss_pct} points; a pipeline fault was found ({faults_txt}): this is a bug to fix, "
                "not a lesson.",
    "pm_flag": " {flag_txt} was visible {before_n} minutes before the entry.",
    "lesson": "{feature_txt} ({family_txt}): refusing such trades changed random trades by {vv_pp} points; "
              "selected, so biased upward. Status: {status_txt}.",
    "playbook": "Rules tested and kept: {validated_n} · tested and dropped: {rejected_n} · in the bot, contradicted "
                "by our data: {contradicted_n} · in the bot, untested: {unsupported_n}",
    "kept": "Rules tested and kept: {k_n} (at most 1 in 10 expected to be a false keep)",
    "independent": "about {n} independent situations (estimated)",
    "version": "The version running since {date_txt} shows skill; the earlier one did not.",
    "exam": "Past-data check ({days}, version {version_txt}): {result_txt}",
}
_FIELDS = string.Formatter()


def lint(text: str) -> list[str]:
    """Every banned word or phrase in ``text`` (lower-cased, sorted, unique)."""
    return sorted({m.group(0).lower() for m in _BANNED_RE.finditer(text or "")})


def fields(name: str) -> list[str]:
    """The field names of a template."""
    return [f for _, f, _, _ in _FIELDS.parse(TEMPLATES[name]) if f]


# --------------------------------------------------------------------------- formatting by suffix


def _finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _text(v: Any) -> str:
    """A ``_txt`` field: a string (control characters blanked, at most TEXT_MAX); None -> ""; anything else -> "?"."""
    if v is None:
        return ""
    if not isinstance(v, str):
        return "?"
    text = "".join(ch if ch.isprintable() else " " for ch in v)
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX - 1] + "…"


def _value(field: str, v: Any) -> str:
    if field.endswith("_txt"):
        return _text(v)
    x = _finite(v)
    if field == "days" or field.endswith("_days"):
        n = 0 if x is None else max(0, int(round(min(x, 1e12))))
        return f"{n:,} day" + ("" if n == 1 else "s")
    if field == "n" or field.endswith("_n"):
        return "0" if x is None else f"{max(0, int(round(min(x, 1e12)))):,}"
    if x is None:
        return "?"
    if field.endswith("_pp"):
        return f"{x:+.1f}"
    if field.endswith("_x"):
        return f"{x:.1f}"
    if field.endswith("_s"):
        return f"{x:.0f}"
    if field.endswith("_usd"):
        return f"{x:.2f}"
    if field.endswith("_pct"):
        return f"{100.0 * x:.0f}"
    if field.endswith("_10"):
        return str(int(round(min(1.0, max(0.0, x)) * 10)))
    if field.endswith("_k"):
        return "?" if x <= 0 else f"{max(1, round(min(1.0 / x, 1e12))):,}"
    raise KeyError(f"template field {field!r} has no known suffix")


def say(name: str, **values: Any) -> str:
    """Fill template ``name``; every field is formatted by its suffix (see the module docstring)."""
    return TEMPLATES[name].format(**{f: _value(f, values.get(f)) for f in fields(name)})


# --------------------------------------------------------------------------- chips and labels


def chip_word(member: str, label: str, *, paper: bool = True) -> str:
    """The chip word of ``member``'s card (raises for a label its kind does not have)."""
    kind = MEMBER_KIND[member]
    if label not in KIND_LABELS[kind]:
        raise ValueError(f"{label} is not a {kind} label")
    if member == "risk" and label in RISK_CHIP_WORDS:
        return RISK_CHIP_WORDS[label]
    if member == "broker" and label == "not_measured" and paper:
        return "Not measured on paper"
    return CHIP_WORDS[kind][label]


def chip_tone(label: str) -> str:
    """``green`` only for skilled / meets_bar, ``red`` for the bad labels, ``grey`` otherwise (never amber)."""
    return "green" if label in GREEN_LABELS else "red" if label in RED_LABELS else "grey"


def label_text(member: str, label: str, *, alpha: float = 0.01, paper: bool = True) -> str:
    """The sentence a card's plain words end with. "Skill shown" only for ``skilled``."""
    chip_word(member, label, paper=paper)  # validates the label for the kind
    if label == "not_measured":
        if member == "judge":
            return say("label_judge_off")
        return say("label_broker_paper" if member == "broker" and paper else "label_not_measured")
    if member == "risk" and label in ("meets_bar", "below_bar"):
        return say("label_within_tolerance" if label == "meets_bar" else "label_over_tolerance")
    return say(f"label_{label}", check_txt=check_pct(alpha))


# --------------------------------------------------------------------------- the team headline (§8.2)


def headline_lines(*, graded: Any, days: Any, practised: Any, practised_window: str = "first_3h",
                   practised_days: Any = None, labels: Mapping[str, str], alpha: float = 0.01) -> list[str]:
    """Headline lines 1-2 from the members' labels."""
    window = PRACTICE_WINDOWS.get(practised_window, PRACTICE_WINDOWS["first_3h"])
    if _finite(practised_days):
        window = say("practised_days", days=practised_days, window_txt=window)
    done = say("practised", n=practised, window_txt=window) if _finite(practised) else say("practised_none")
    line1 = say("practice", graded_n=graded, days=days, practised_txt=done)
    chance = [m for m in MEMBER_NAMES if MEMBER_KIND[m] == "chance"]
    collecting = [m for m in chance if labels.get(m, "not_enough") == "not_enough"]
    off = [m for m in chance if labels.get(m) == "not_measured"]
    line2 = say("skills", check_txt=check_pct(alpha), k_n=sum(labels.get(m) == "skilled" for m in chance),
                of_n=SKILLS_MEASURABLE)
    parts = []
    if collecting:
        parts.append(say("collecting", n=len(collecting), names_txt=", ".join(MEMBER_NAMES[m] for m in collecting)))
    parts += [say("jev_off") if m == "judge" else say("member_off", name_txt=MEMBER_NAMES[m]) for m in off]
    return [line1, line2 + (" " + "; ".join(parts) + "." if parts else "")]


def bars_line(words: Mapping[str, str]) -> str:
    """``words``: the chip words of crawler, broker and risk (shown in lower case)."""
    return say("bars", **{f"{m}_txt": (words.get(m) or "not measured").lower() for m in ("crawler", "broker", "risk")})


def money_line(coach_state: str | None) -> str:
    """Always from the Coach card's state; it changes only for paper_champion, live_ready or live."""
    return say(f"money_{coach_state}" if coach_state in COACH_MONEY_STATES else "money_none")


def independent_line(n: Any) -> str:
    """"about N independent situations (estimated)", or "" while there is no estimate (< 15 forward days)."""
    return "" if _finite(n) is None else say("independent", n=n)


# --------------------------------------------------------------------------- loss library (§6)


def loss_types_line(items: Sequence[Mapping[str, Any]]) -> str:
    """``items``: [{type, n, expected}] most frequent first; the first one spells out what "expected" means."""
    parts = [say("loss_first" if i == 0 else "loss_next", name_txt=LOSS_NAMES.get(str(item.get("type")), "other"),
                 n=item.get("n"), e_x=item.get("expected")) for i, item in enumerate(items)]
    return say("loss_types", items_txt=" · ".join(parts)) if parts else say("loss_types_none")


def pm_note(*, primary: str, x: Any, base_rate: Any = None, drop: Any = None, minutes_after_entry: Any = None,
            gap: Any = None, faults: Sequence[str] = (), flag: str | None = None,
            flag_minutes_before: Any = None) -> str:
    """The one templated sentence of a post-mortem (``x``, ``drop``, ``gap`` as fractions)."""
    xv = _finite(x)
    result = "Lost" if xv is not None and xv < 0 else "Made" if xv is not None and xv > 0 else "Ended at"
    loss = None if xv is None else abs(xv)
    if primary == "pipeline_fault":
        text = say("pm_fault", result_txt=result, loss_pct=loss,
                   faults_txt=", ".join(sorted({str(f)[:40] for f in faults})) or "unspecified")
    elif primary == "rug_missed":
        g = _finite(gap)
        text = say("pm_rug", result_txt=result, loss_pct=loss, drop_pct=drop, after_n=minutes_after_entry,
                   gap_pct=None if g is None else abs(g), rate_10=base_rate)
    else:
        text = say("pm_other", result_txt=result, loss_pct=loss, name_txt=LOSS_NAMES.get(primary, "other"),
                   rate_10=base_rate)
    if flag:
        text += say("pm_flag", flag_txt=str(flag)[:60], before_n=flag_minutes_before)
    return text
