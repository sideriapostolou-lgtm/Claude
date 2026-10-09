"""The team's report cards on the one page (docs/EXPERIENCE.md §8-§9): ``/api/page.experience`` built from
``nightcrawler.experience.state.experience_state`` (another team's module: absent here unless a test installs a
fake), with the static playbook as the fallback for the playbook counts.

Three sources, like the learning card: ``state`` (a sanitized state), ``missing`` (the module is not installed)
and ``error`` (it raised, returned junk, or broke an honesty rule: a green chip whose band does not clear chance
or the bar, a card of the wrong kind, a Broker graded on paper, a skill count that disagrees with the chips).
Chip words always come from the label (§5.1), never from the state's own text; the money line only ever says
"not shown yet" unless the Coach itself has a champion; nothing here changes the checklist or the banners."""

from __future__ import annotations

import copy
import json
import re
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.dashboard import DashboardServer, build_state
from nightcrawler.ledger import Ledger
from nightcrawler.page import MEMBERS, render_page_html
from nightcrawler.pagestate import EXPERIENCE_CAVEAT, EXPERIENCE_MONEY_LINE, build_page_state, experience_card
from nightcrawler.teamroom import TeamRoom

NOW = 1_791_475_200.0  # 2026-10-08T16:00:00Z
XSS = "<img src=x onerror=alert(1)>"
SECRET = "sk-ant-api03-TOPSECRETanthropicKEY0123456789"
MEMBER_IDS = [mid for mid, _, _ in MEMBERS]
EXPERIENCE_KEYS = {"source", "headline", "bars_line", "money_line", "caveat", "team", "members", "loss_types_week",
                   "lessons", "playbook"}
TEAM_KEYS = {"graded", "days", "practised", "practised_window", "skills_shown", "skills_measurable", "collecting",
             "not_measured", "updated_at"}
MEMBER_KEYS = {"kind", "label", "chip", "line", "graded", "days", "practised", "metrics", "exam", "trend",
               "version_line", "independent", "lessons", "coverage", "budget_left"}
METRIC_KEYS = {"name", "value", "lo", "hi", "baseline", "unit", "text"}
PLAYBOOK_KEYS = {"validated", "rejected", "in_bot_contradicted", "in_bot_unsupported", "testing", "false_keep_bound"}
#: The static playbook's initial statuses (docs/EXPERIENCE.md §7.1).
STATIC_PLAYBOOK = {"validated": 0, "rejected": 0, "in_bot_contradicted": 6, "in_bot_unsupported": 5, "testing": 2,
                   "false_keep_bound": "1 in 10"}
#: docs/EXPERIENCE.md §8.4: never in an owner-facing string (word boundaries, any case).
BANNED = re.compile(r"\b(?:expert|pro|master|level|xp|rank|elite|guaranteed|smart money|win rate|winning streak|"
                    r"profitable|profit|studied|experienced|edge|learned|money added|proven|beats|improving|"
                    r"improved)\b", re.IGNORECASE)
JARGON = re.compile(r"\b(?:bps|lamports?|mint|slippage|mcap|prefilter|kv|ledger)\b", re.IGNORECASE)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture(autouse=True)
def modules_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both modules are built by other teams: ABSENT here unless a test installs a fake."""
    monkeypatch.setitem(sys.modules, "nightcrawler.learn.card", None)
    monkeypatch.setitem(sys.modules, "nightcrawler.experience.state", None)


def install_state(monkeypatch: pytest.MonkeyPatch, func: Callable[..., Any]) -> None:
    """Make ``nightcrawler.experience.state.experience_state`` importable and be ``func``."""
    package = types.ModuleType("nightcrawler.experience")
    package.__path__ = []
    module = types.ModuleType("nightcrawler.experience.state")
    module.experience_state = func  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nightcrawler.experience", package)
    monkeypatch.setitem(sys.modules, "nightcrawler.experience.state", module)


def install_card(monkeypatch: pytest.MonkeyPatch, card: dict[str, Any]) -> None:
    package = types.ModuleType("nightcrawler.learn")
    package.__path__ = []
    module = types.ModuleType("nightcrawler.learn.card")
    module.learning_card_state = lambda settings, now: card  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nightcrawler.learn", package)
    monkeypatch.setitem(sys.modules, "nightcrawler.learn.card", module)


def metric(name: str, value: float | None, lo: float | None = None, hi: float | None = None,
           baseline: float | None = None, unit: str = "pp", text: str = "") -> dict[str, Any]:
    return {"name": name, "value": value, "lo": lo, "hi": hi, "baseline": baseline, "unit": unit, "text": text}


def card(kind: str, label: str, chip: str, *metrics: dict[str, Any], **extra: Any) -> dict[str, Any]:
    out = {"kind": kind, "label": label, "chip": chip, "line": "", "graded": None, "days": None, "practised": None,
           "metrics": list(metrics), "exam": None, "trend": [], "version_line": "", "independent": "",
           "lessons": {"open": 0, "testing": 0, "adopted": 0, "rejected": 0}, "coverage": "", "budget_left": None}
    out.update(extra)
    return out


def full_state() -> dict[str, Any]:
    """About two weeks in (the §9 phone mock-up): every card collecting or without skill, Crawler at its bar."""
    return {
        "source": "state",
        "headline": ["Practice record: 16,240 new coins graded over 14 days; 3,912 past coins practised "
                     "(first 3 hours only).",
                     "Skills shown (99% check): 0 of 4. Still collecting: 2 (Radar, Cocoon); Jev is off."],
        "bars_line": "Bars: Crawler meets the bar · Broker not measured on paper · Risk collecting.",
        "money_line": EXPERIENCE_MONEY_LINE,
        "caveat": EXPERIENCE_CAVEAT,
        "team": {"graded": 16_240, "days": 14, "practised": 3_912, "practised_window": "first 3 hours only",
                 "skills_shown": 0, "skills_measurable": 4, "collecting": 2, "not_measured": ["Jev"],
                 "updated_at": NOW - 600},
        "members": {
            "cocoon": card("chance", "not_enough", "Collecting",
                           metric("Random trade after its blocks", -0.4, -1.2, 0.5, 0.0,
                                  text="trades still lose on average"),
                           metric("Rugs blocked", 1.4, 1.1, 1.8, 1.0, "ratio", "1.4× a coin flip (3 vs 2 of 10)"),
                           metric("Good coins wrongly blocked", 0.17, unit="share", text="1 in 6"),
                           line="Cocoon checked 4,212 coins on 14 days.", graded=4_212, days=14,
                           coverage="Checked 31% of graded coins"),
            "strategy": card("chance", "no_skill_yet", "No skill yet",
                             metric("Entries compared with random entries", -2.1, -6.3, 2.0, 0.0),
                             metric("After all costs", -4.8, -7.0, -2.5, 0.0), graded=61, days=14, practised=3_912,
                             trend=[[NOW - 21 * 86_400, -3.0, -9.0, 3.0], [NOW - 14 * 86_400, -2.5, -7.5, 2.5],
                                    [NOW - 7 * 86_400, -2.1, -6.3, 2.0]],
                             exam={"split": "confirm", "version12": "3fa1c2d4e5f6", "date": "2026-10-20",
                                   "result": "not passed", "current": False},
                             lessons={"open": 1, "testing": 0, "adopted": 0, "rejected": 0}, budget_left=0.01),
            "radar": card("chance", "not_enough", "Collecting", graded=61, days=14),
            "judge": card("chance", "not_measured", "Not measured", line="Jev is off."),
            "crawler": card("bar", "meets_bar", "Meets the bar",
                            metric("New graduates seen within 15 minutes", 0.93, 0.91, 0.95, 0.90, "share"),
                            graded=16_240, days=14),
            "broker": card("bar", "not_measured", "Not measured", metric("Decision to fill", 3.2, unit="s")),
            "risk": card("bar", "not_enough", "Collecting", metric("One rug costs", 0.19, unit="share")),
            "coach": card("self_check", "checks_pass", "Checks pass",
                          metric("Random-entry control", -4.8, -6.0, -3.6, -1.0)),
            "receipts": card("self_check", "checks_pass", "Checks pass"),
        },
        "loss_types_week": [
            {"type": "rug_missed", "n": 4, "expected": 3.8,
             "text": "Lost 31 points: the price fell 88% in one minute, 14 minutes after entry."},
            {"type": "bad_entry", "n": 6, "expected": 5.1, "text": ""},
            {"type": "cost_eaten", "n": 2, "expected": 2.4, "text": ""},
        ],
        "lessons": [{"id": "L-2026W42-1", "status": "open",
                     "text": "Fast coins 0-30 min after graduation: test a veto on new coins"}],
        "playbook": {"validated": 0, "rejected": 0, "in_bot_contradicted": 6, "in_bot_unsupported": 5,
                     "testing": 2, "false_keep_bound": "1 in 10"},
    }


def experience(ledger: Ledger, settings: Settings, now: float = NOW) -> dict[str, Any]:
    section: dict[str, Any] = build_page_state(ledger, settings, now)["experience"]
    return section


def live_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_SECRET="x" * 88,
                         DASHBOARD_TOKEN="dash-token-correct-horse-battery-staple")


# --------------------------------------------------------------------------- the three sources


def test_missing_module_gives_every_key_and_the_static_playbook(ledger: Ledger, settings: Settings) -> None:
    x = experience(ledger, settings)
    assert set(x) == EXPERIENCE_KEYS and set(x["team"]) == TEAM_KEYS and set(x["playbook"]) == PLAYBOOK_KEYS
    assert x["source"] == "missing" and x["members"] == {} and x["headline"] == ["", ""]
    assert x["bars_line"] == "" and x["money_line"] == "" and x["caveat"] == EXPERIENCE_CAVEAT
    assert x["team"] == {"graded": None, "days": None, "practised": None, "practised_window": "",
                         "skills_shown": None, "skills_measurable": 4, "collecting": None, "not_measured": [],
                         "updated_at": None}
    assert x["loss_types_week"] == [] and x["lessons"] == []
    assert x["playbook"] == STATIC_PLAYBOOK  # the playbook ships with the bot: known before any report card
    json.dumps(x, allow_nan=False)


@pytest.mark.parametrize("content", [None, "not json", '{"rules": 5}', '{"rules": [{"id": "G01"}]}', "[]"])
def test_an_unreadable_static_playbook_gives_unknown_counts_not_zeros(
        ledger: Ledger, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        content: str | None) -> None:
    path = tmp_path / "playbook.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr("nightcrawler.pagestate.PLAYBOOK_PATH", path)
    playbook = experience(ledger, settings)["playbook"]
    assert playbook == {"validated": None, "rejected": None, "in_bot_contradicted": None, "in_bot_unsupported": None,
                        "testing": None, "false_keep_bound": "1 in 10"}  # "0 contradicted" would be a false claim


def test_a_real_state_is_shown_safely(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                      make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(ANTHROPIC_API_KEY=SECRET)
    calls: list[tuple[Settings, float]] = []
    state = full_state()
    state["headline"][0] += " " + XSS + " " + SECRET
    state["members"]["cocoon"]["line"] = "x" * 5_000
    state["members"]["cocoon"]["metrics"][0]["name"] += XSS
    state["lessons"][0]["text"] += " " + SECRET

    def experience_state(settings: Settings, now: float) -> dict[str, Any]:
        calls.append((settings, now))
        return state

    install_state(monkeypatch, experience_state)
    x = experience(ledger, settings)
    assert calls == [(settings, NOW)]
    assert x["source"] == "state" and set(x) == EXPERIENCE_KEYS and set(x["team"]) == TEAM_KEYS
    assert list(x["members"]) == MEMBER_IDS  # the page's order
    for mid, m in x["members"].items():
        assert set(m) == MEMBER_KEYS, mid
        assert all(set(item) == METRIC_KEYS for item in m["metrics"]), mid
    assert XSS in x["headline"][0] and SECRET not in json.dumps(x) and "[REDACTED]" in x["headline"][0]
    assert x["members"]["cocoon"]["metrics"][0]["name"].endswith(XSS)  # text, inserted with textContent
    assert len(x["members"]["cocoon"]["line"]) <= 320
    assert x["team"] == {**full_state()["team"]}
    assert x["members"]["strategy"]["exam"] == full_state()["members"]["strategy"]["exam"]
    assert x["members"]["strategy"]["trend"] == full_state()["members"]["strategy"]["trend"]
    assert x["members"]["crawler"]["chip"] == "Meets the bar" and x["members"]["judge"]["chip"] == "Not measured"
    assert x["loss_types_week"] == full_state()["loss_types_week"]
    assert x["playbook"] == STATIC_PLAYBOOK and x["money_line"] == EXPERIENCE_MONEY_LINE
    assert x["caveat"] == EXPERIENCE_CAVEAT
    json.dumps(x, allow_nan=False)


def test_the_state_may_say_it_has_nothing_yet(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                              settings: Settings) -> None:
    for source in ("missing", "error"):
        install_state(monkeypatch, lambda settings, now, source=source: {"source": source, "members": {}})
        x = experience(ledger, settings)
        assert x["source"] == source and x["members"] == {} and x["playbook"] == STATIC_PLAYBOOK


def test_a_broken_module_is_an_error_never_an_exception(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                        settings: Settings) -> None:
    def boom(settings: Settings, now: float) -> dict[str, Any]:
        raise RuntimeError("boom")

    install_state(monkeypatch, boom)
    x = experience(ledger, settings)
    assert x["source"] == "error" and x["members"] == {} and x["playbook"] == STATIC_PLAYBOOK
    # installed, but its own import broke (a dependency is missing): an error, not "not installed"
    package = types.ModuleType("nightcrawler.experience")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "nightcrawler.experience", package)
    monkeypatch.delitem(sys.modules, "nightcrawler.experience.state")

    class Finder:
        @staticmethod
        def find_spec(name: str, path: Any = None, target: Any = None) -> Any:
            if name == "nightcrawler.experience.state":
                raise ModuleNotFoundError("No module named 'scipy'", name="scipy")
            return None

    monkeypatch.setattr(sys, "meta_path", [Finder(), *sys.meta_path])
    assert experience(ledger, settings)["source"] == "error"


@pytest.mark.parametrize("junk", [
    None, [], "text", 42, {}, {"members": "x"}, {"members": {"cocoon": None}}, {"headline": 7, "members": []},
    {"headline": ["only one line"], "members": {"cocoon": {"kind": "chance"}}},
    {"members": {"strategy": card("chance", "no_skill_yet", "x", *[metric("m", float("nan"), float("-inf"),
                                                                           float("inf"), 1e300)] * 50,
                                  trend=[[1, 2], None, "x", [NOW, 1, 2, 3]] * 40, graded=-5, days=True,
                                  exam={"version12": 5, "current": "yes"}, budget_left=7,
                                  lessons={"open": -1, "testing": "two"})},
     "loss_types_week": [{"type": "<b>", "n": "many"}, None] * 30, "lessons": [7] * 30,
     "team": {"graded": 10**20, "updated_at": NOW * 1000, "not_measured": [XSS * 40] * 50},
     "playbook": {"validated": "lots", "in_bot_contradicted": -1}},
])
def test_junk_never_raises_and_stays_bounded(monkeypatch: pytest.MonkeyPatch, ledger: Ledger, settings: Settings,
                                             junk: Any) -> None:
    install_state(monkeypatch, lambda settings, now: copy.deepcopy(junk))
    x = experience(ledger, settings)
    assert x["source"] in ("state", "error") and set(x) == EXPERIENCE_KEYS
    assert x["caveat"] == EXPERIENCE_CAVEAT and len(x["headline"]) == 2
    assert len(x["loss_types_week"]) <= 3 and len(x["lessons"]) <= 3 and len(x["team"]["not_measured"]) <= 9
    for m in x["members"].values():
        assert len(m["metrics"]) <= 3 and len(m["trend"]) <= 8
        assert m["graded"] is None or m["graded"] >= 0
        for item in m["metrics"]:
            assert all(v is None or abs(v) < 1e9 for v in (item["value"], item["lo"], item["hi"], item["baseline"]))
    updated = x["team"]["updated_at"]
    assert updated is None or updated <= NOW + 60  # a millisecond stamp is not "updated just now"
    json.dumps(x, allow_nan=False)
    assert len(json.dumps(x)) < 20_000


def test_a_maximal_state_keeps_the_page_small(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                              settings: Settings) -> None:
    state = full_state()
    long = "y" * 2_000
    for m in state["members"].values():
        m.update(line=long, version_line=long, independent=long, coverage=long,
                 metrics=[metric(long, 1.0, 0.0, 2.0, -1.0, text=long)] * 10,
                 trend=[[NOW, 1.0, 0.0, 2.0]] * 50)
    state["loss_types_week"] = [{"type": "rug_missed", "n": 1, "expected": 1.0, "text": long}] * 10
    state["lessons"] = [{"id": long, "status": "open", "text": long}] * 10
    install_state(monkeypatch, lambda settings, now: state)
    x = experience(ledger, settings)
    assert x["source"] == "state"
    assert len(json.dumps(x, ensure_ascii=False)) < 24_000


# --------------------------------------------------------------------------- honesty rules at the boundary


def test_chip_words_come_from_the_label_never_from_the_state(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                             settings: Settings) -> None:
    state = full_state()
    state["members"]["cocoon"]["chip"] = "Skill shown"  # a label of "not_enough" can never read as skill
    state["members"]["radar"]["chip"] = "Elite radar"
    state["members"]["risk"] = card("bar", "meets_bar", "Meets the bar",
                                    metric("Chance of losing half in a month", 0.03, 0.01, 0.04, 0.05, "share"))
    install_state(monkeypatch, lambda settings, now: state)
    members = experience(ledger, settings)["members"]
    assert members["cocoon"]["chip"] == "Collecting" and members["radar"]["chip"] == "Collecting"
    assert members["risk"]["chip"] == "Within tolerance"  # Risk's own bar words (§5.1)
    words = {m["chip"] for m in members.values()}
    assert words <= {"Not measured", "Collecting", "No skill yet", "Skill shown", "Worse than chance",
                     "Meets the bar", "Below the bar", "Within tolerance", "Over tolerance", "Not built yet",
                     "Checks pass", "Check failed"}


def skilled_cocoon(lo: float | None, hi: float | None, baseline: float | None = 0.0) -> dict[str, Any]:
    return card("chance", "skilled", "Skill shown", metric("Random trade after its blocks", 1.5, lo, hi, baseline))


@pytest.mark.parametrize(("mid", "member", "ok"), [
    ("cocoon", skilled_cocoon(0.4, 2.6), True),
    ("cocoon", skilled_cocoon(-0.1, 2.6), False),  # the band crosses chance
    ("cocoon", skilled_cocoon(0.0, 2.6), False),  # touching chance is not clearing it
    ("cocoon", skilled_cocoon(None, None), False),  # no band, no claim
    ("cocoon", skilled_cocoon(0.4, 2.6, None), False),
    ("cocoon", card("chance", "skilled", "Skill shown"), False),  # no metric at all
    ("strategy", card("chance", "worse", "Worse than chance", metric("Entries", -3.0, -5.0, -1.0, 0.0)), True),
    ("strategy", card("chance", "worse", "Worse than chance", metric("Entries", -3.0, -5.0, 0.5, 0.0)), False),
    ("crawler", card("bar", "meets_bar", "Meets the bar", metric("Seen", 0.93, 0.90, 0.95, 0.90, "share")), True),
    ("crawler", card("bar", "meets_bar", "Meets the bar", metric("Seen", 0.93, 0.89, 0.95, 0.90, "share")), False),
    ("risk", card("bar", "meets_bar", "Within tolerance", metric("Ruin", 0.03, 0.01, 0.05, 0.05, "share")), True),
    ("risk", card("bar", "meets_bar", "Within tolerance", metric("Ruin", 0.03, 0.01, 0.06, 0.05, "share")), False),
    ("risk", card("bar", "below_bar", "Over tolerance"), True),  # a broken limit needs no band to be bad news
    ("crawler", card("chance", "skilled", "Skill shown", metric("Seen", 0.9, 0.8, 1.0, 0.5, "share")), False),
    ("coach", card("chance", "skilled", "Skill shown", metric("x", 1.0, 0.5, 1.5, 0.0)), False),  # never green
    ("coach", card("self_check", "meets_bar", "Meets the bar"), False),
    ("judge", card("chance", "elite", "Elite"), False),
    ("broker", card("bar", "meets_bar", "Meets the bar", metric("Shortfall", 0.1, -0.2, 0.4, 0.5)), False),  # paper
    ("broker", card("bar", "not_enough", "Collecting"), False),  # on paper the Broker is never graded
    ("broker", card("bar", "not_measured", "Not measured"), True),
])
def test_claims_the_band_does_not_back_are_refused(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                   settings: Settings, mid: str, member: dict[str, Any],
                                                   ok: bool) -> None:
    state = full_state()
    state["members"][mid] = member
    state["team"]["skills_shown"] = 1 if member["label"] == "skilled" and ok else 0
    install_state(monkeypatch, lambda settings, now: state)
    x = experience(ledger, settings)
    assert x["source"] == ("state" if ok else "error"), (mid, member["label"])
    if ok:
        assert x["members"][mid]["label"] == member["label"]
    else:
        assert x["members"] == {} and x["headline"] == ["", ""]  # nothing of a state that broke a rule


def test_live_broker_can_be_graded(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                   make_settings: Callable[..., Settings]) -> None:
    state = full_state()
    state["members"]["broker"] = card("bar", "meets_bar", "Meets the bar",
                                      metric("Shortfall against the model", 0.1, -0.2, 0.4, 0.5))
    install_state(monkeypatch, lambda settings, now: state)
    assert experience(ledger, live_settings(make_settings))["members"]["broker"]["chip"] == "Meets the bar"


def test_the_skill_count_must_match_the_chips(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                              settings: Settings) -> None:
    state = full_state()
    state["team"]["skills_shown"] = 1  # the headline would say 1 of 4 while every chip says otherwise
    install_state(monkeypatch, lambda settings, now: state)
    assert experience(ledger, settings)["source"] == "error"
    state["team"]["skills_shown"] = None
    assert experience(ledger, settings)["team"]["skills_shown"] == 0  # counted from the chips
    state["team"]["skills_measurable"] = 9
    assert experience(ledger, settings)["team"]["skills_measurable"] == 4  # Cocoon, Strategy, Radar, Jev


def test_the_money_line_only_moves_when_the_coach_has_a_champion(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                                 settings: Settings) -> None:
    state = full_state()
    state["money_line"] = "Making money: shown on paper."
    install_state(monkeypatch, lambda settings, now: state)
    assert experience(ledger, settings)["money_line"] == EXPERIENCE_MONEY_LINE  # no learning card at all
    for coach_state, line in (("practice", EXPERIENCE_MONEY_LINE), ("collecting", EXPERIENCE_MONEY_LINE),
                              ("paper_champion", "Making money: shown on paper."),
                              ("live", "Making money: shown on paper.")):
        install_card(monkeypatch, {"headline": "learning", "state": coach_state})
        assert experience(ledger, settings)["money_line"] == line, coach_state


def test_report_cards_never_change_the_checklist_or_the_banners(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                                settings: Settings) -> None:
    """Experience can never turn real trading ON: an all-green state leaves "ready" and the banners alone."""
    before = build_page_state(ledger, settings, NOW)
    state = full_state()
    for mid in ("cocoon", "strategy", "radar", "judge"):
        state["members"][mid] = skilled_cocoon(0.4, 2.6)
    state["team"]["skills_shown"] = 4
    state["money_line"] = "Making money: shown."
    install_state(monkeypatch, lambda settings, now: state)
    after = build_page_state(ledger, settings, NOW)
    assert after["experience"]["source"] == "state" and after["experience"]["team"]["skills_shown"] == 4
    assert after["ready"] == before["ready"] and after["alerts"] == before["alerts"]
    assert after["learning"] == before["learning"] and after["learning"]["rule"] is None


def test_the_state_is_read_at_most_once_a_minute(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    calls: list[float] = []

    def experience_state(settings: Settings, now: float) -> dict[str, Any]:
        calls.append(now)
        return full_state()

    install_state(monkeypatch, experience_state)
    memory: dict[str, Any] = {}
    empty_card = {"source": "missing", "state": None}
    for now in (NOW, NOW + 30, NOW + 59):
        assert experience_card(settings, now, empty_card, memory)["source"] == "state"
    assert calls == [NOW]
    experience_card(settings, NOW + 61, empty_card, memory)
    assert calls == [NOW, NOW + 61]
    experience_card(settings, NOW + 62, empty_card)  # no memory: always fresh
    assert len(calls) == 3


def test_the_api_route_carries_the_experience_key(ledger: Ledger, settings: Settings) -> None:
    team = TeamRoom(settings, ledger=ledger, clock=FakeClock(NOW), environ={})
    server = DashboardServer(settings, lambda: build_state(ledger, settings, NOW, {}), host="127.0.0.1", port=0,
                             team=team)
    server.start()
    try:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port, timeout=10)
        conn.request("GET", "/api/page")
        body = json.loads(conn.getresponse().read())
        conn.close()
    finally:
        server.stop()
    assert body["experience"]["source"] == "missing" and body["experience"]["playbook"] == STATIC_PLAYBOOK


# --------------------------------------------------------------------------- the page


def page_script(settings: Settings) -> str:
    (script,) = re.findall(r"<script>(.*?)</script>", render_page_html(settings), flags=re.DOTALL)
    return script


def experience_script(settings: Settings) -> str:
    script = page_script(settings)
    start = script.index("// ---------------------------------------------------------------- B2. report cards")
    end = script.index("// ---------------------------------------------------------------- C. trades")
    return script[start:end]


def test_the_report_cards_live_inside_the_team_card(settings: Settings) -> None:
    html = render_page_html(settings)
    team = html[html.index('<section class="card" id="team">'):html.index('<section class="card" id="trades">')]
    assert team.index('id="xp-head"') < team.index('class="members"') < team.index('id="xp-playbook"')
    assert html.count('class="graded"') == len(MEMBERS)  # "Graded on 4,212 coins · 14 days" under each row
    ids = re.findall(r'<section class="card" id="([a-z]+)"', html)
    assert ids == ["money", "team", "trades", "learning", "ready", "receipts", "usage"]  # no new card


def test_the_page_draws_range_bars_and_chips_as_text_only(settings: Settings) -> None:
    script = experience_script(settings)
    for name in ("function rangeBar(", "function skillChip(", "function renderExperience(", "function reportCard(",
                 "function coachBlock(", "function sparkline("):
        assert name in script, name
    assert ".style.left" in script and ".style.width" in script  # positions through the CSSOM: CSP-safe
    assert 'setAttribute("aria-label"' in script and "likely between" in script
    assert "renderTeam(s.team, s.experience)" in page_script(settings)
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink


def test_only_a_band_that_clears_chance_or_the_bar_is_green(settings: Settings) -> None:
    """Green for "skilled" and "meets_bar" only; red for the bad side; grey otherwise (never amber). The chip WORD
    comes from the data, so the page itself never writes "Skill shown"."""
    script = experience_script(settings)
    assert 'const GOOD_LABELS = ["skilled", "meets_bar"]' in script
    assert 'const BAD_LABELS = ["worse", "below_bar", "check_failed"]' in script
    assert "Skill shown" not in page_script(settings)
    from nightcrawler.page import _STYLE

    assert ".skill-chip.good{" in _STYLE and ".skill-chip.bad{" in _STYLE and ".skill-chip.warn" not in _STYLE


def test_the_report_card_words_pass_the_lint(settings: Settings) -> None:
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', experience_script(settings))
    words = [s for s in strings if " " in s]
    assert words
    for s in words:
        assert not BANNED.search(s), s
        assert not JARGON.search(s), s
        assert "win rate" not in s.lower()
    assert "Avoiding losses is not the same as making money." == EXPERIENCE_CAVEAT
    assert not BANNED.search(EXPERIENCE_CAVEAT + " " + EXPERIENCE_MONEY_LINE)


def test_new_colours_exist_in_light_and_dark(settings: Settings) -> None:
    from nightcrawler.page import _STYLE

    light = dict(re.findall(r"(--[a-z0-9-]+):([^;}]+)", _STYLE.split("@media (prefers-color-scheme:dark)")[0]))
    dark_block = _STYLE.split("@media (prefers-color-scheme:dark)")[1].split("}}")[0]
    dark = dict(re.findall(r"(--[a-z0-9-]+):([^;}]+)", dark_block))
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", _STYLE))
    assert used <= set(light) and used <= set(dark), used - set(light) - set(dark)
    assert ".rbar" in _STYLE and ".spark" in _STYLE
