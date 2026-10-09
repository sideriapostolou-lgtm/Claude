"""Weekly lessons (docs/EXPERIENCE.md §6.5, §6.6, §11 ``test_lessons``, ``test_split_guards``).

* a pure-noise feature on outcome-labelled trades opens a lesson in <= 10 % of 500 runs (none at the fixture seed);
* the DP fact 5 fixture (raw -4.6 pp, matched -0.4 pp: the apparent re-entry "mistake" was coin age) opens none;
* a group opens once per taxonomy version; at most 3 lessons a week, the largest e-value first;
* lessons are hypothesis drafts only: the code writes nothing (AST plus a filesystem sandbox);
* the miner refuses every split but ``train`` and forward rows (``SplitLocked``); ``final_train`` yields no lesson.
"""

from __future__ import annotations

import ast
import builtins
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import nightcrawler.experience
from nightcrawler.experience import features as feat
from nightcrawler.experience import stats
from nightcrawler.experience.constants import AGE_BAND_NAMES, CELL_FAMILIES, LESSON_WEEKLY_CAP, TAXONOMY_VERSION

DAY0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
EXPERIENCE = Path(nightcrawler.experience.__file__).parent


def day(i: int) -> str:
    return (DAY0 + timedelta(days=i)).strftime("%Y-%m-%d")


def clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def coins(rng: random.Random, days: int, per_day: int, planted: dict[str, float] | None = None,
          host: str = "R", rug_share: float = 0.15) -> list[dict[str, Any]]:
    """Outcome-labelled random entries: rugs (x ~ -0.95) and the rest. ``planted``: feature -> the share of the
    RUGS it flags (it never flags anything else). Every row also carries a pure-noise feature."""
    planted = planted or {}
    rows = []
    for d in range(days):
        for i in range(per_day):
            bad = rng.random() < rug_share
            flags = {f: bad and rng.random() < share for f, share in planted.items()}
            x = clip(rng.gauss(-0.95, 0.05)) if bad else clip(rng.gauss(-0.03, 0.25))
            flags["noise"] = rng.random() < 0.3
            rows.append({"mint": f"M{d}-{i}", "host": host, "source": "forward", "day": day(d), "x": x, "bad": bad,
                         "operator": f"op{rng.randrange(5000)}", "speed": rng.choice(("fast", "slow")),
                         "age_band": rng.choice(AGE_BAND_NAMES), "features": flags})
    return rows


def test_ebh_selects_the_largest_e_values_that_clear_their_rank() -> None:
    assert stats.ebh({"a": 100.0, "b": 30.0, "c": 1.0, "d": 0.5}, q=0.1) == ["a", "b"]
    assert stats.ebh({"a": 39.0, "b": 1.0, "c": 1.0, "d": 1.0}, q=0.1) == []
    assert stats.ebh({}, q=0.1) == []
    assert stats.ebh({"x": 10.0}, q=0.1) == ["x"]


def test_a_pure_noise_feature_rarely_opens_a_lesson() -> None:
    opened = 0
    for run in range(500):
        out = feat.weekly_lessons(coins(random.Random(run), 21, 25), features=("noise",))
        assert out["examined"] <= len(CELL_FAMILIES)
        opened += bool(out["opened"])
        if run == 0:
            assert out["opened"] == [], "the fixture seed opens nothing"
    assert opened <= 50  # 10 % of 500


def test_dp_fact_5_the_confounded_re_entry_mistake_opens_nothing() -> None:
    """Re-entry after a stop looked -4.6 pp worse raw, -0.4 pp matched: re-entries were mostly in young coins."""
    rng = random.Random(5)
    band_mean = dict(zip(AGE_BAND_NAMES, (-0.14, -0.06, -0.04, -0.03), strict=True))
    share = dict(zip(AGE_BAND_NAMES, (0.75, 0.08, 0.08, 0.08), strict=True))
    rows = []
    for d in range(60):
        for i in range(30):
            band = rng.choice(AGE_BAND_NAMES)
            reentry = rng.random() < share[band]
            x = clip(rng.gauss(band_mean[band] - (0.004 if reentry else 0.0), 0.25))
            rows.append({"mint": f"T{d}-{i}", "host": "S", "source": "paper", "day": day(d), "x": x, "bad": x < -0.5,
                         "operator": f"o{rng.randrange(3000)}", "speed": rng.choice(("fast", "slow")),
                         "age_band": band, "features": {"reentry_after_stop": reentry}})
    flagged = [r["x"] for r in rows if r["features"]["reentry_after_stop"]]
    clean = [r["x"] for r in rows if not r["features"]["reentry_after_stop"]]
    raw = sum(flagged) / len(flagged) - sum(clean) / len(clean)
    assert raw < -0.04  # what an unmatched post-mortem "finds"
    out = feat.weekly_lessons(rows, features=("reentry_after_stop",), host="S")
    assert out["opened"] == [] and out["selected"] == []
    record = feat.group_record(rows, "reentry_after_stop", "all", host="S")
    assert abs(record["vv_pp"]) < 1.0  # matched within cells, refusing re-entries is worth ~nothing


def strong_rows() -> list[dict[str, Any]]:
    """120 days in which five features each flag most rugs (danger4 the most)."""
    planted = {f"danger{k}": 0.8 + 0.05 * k for k in range(5)}
    return coins(random.Random(9), 120, 25, planted, rug_share=0.35)


def test_a_real_effect_opens_a_hypothesis_draft_never_a_change() -> None:
    out = feat.weekly_lessons(strong_rows(), features=("danger4", "noise"), nominated_by={"danger4": ["rug_missed"]})
    assert [d["group"] for d in out["opened"]] == [{"feature": "danger4", "family": "all", "host": "R"}]
    draft = out["opened"][0]
    assert set(draft) == {"lesson_id", "group", "evidence", "taxonomy_ver"}
    assert draft["taxonomy_ver"] == TAXONOMY_VERSION and draft["lesson_id"] == feat.lesson_id("danger4", "all", "R")
    ev = draft["evidence"]
    assert ev["selected_biased_upward"] is True and ev["power_plan_pp"] == pytest.approx(ev["vv_pp"] / 2)
    assert ev["vv_pp"] > 10 and ev["flagged_losers"] >= 10 and ev["operators"] >= 5 and ev["days"] >= 3
    assert ev["nominated_by"] == ["rug_missed"] and ev["test_on"] == "forward coins created after this receipt"
    assert ev["examined_groups"] == out["examined"] and ev["lift"] > 1


def test_a_group_opens_once_per_taxonomy_version() -> None:
    rows = strong_rows()
    first = feat.weekly_lessons(rows, features=("danger4",))
    ids = [d["lesson_id"] for d in first["opened"]]
    assert ids
    assert feat.weekly_lessons(rows, features=("danger4",), opened=ids)["opened"] == []
    again = feat.weekly_lessons(rows, features=("danger4",), opened=ids, taxonomy_ver="0" * 64)
    assert [d["group"] for d in again["opened"]] == [d["group"] for d in first["opened"]]


def test_at_most_three_lessons_a_week_largest_e_value_first() -> None:
    out = feat.weekly_lessons(strong_rows(), features=tuple(f"danger{k}" for k in range(5)))
    assert len(out["selected"]) >= 5 and len(out["opened"]) == LESSON_WEEKLY_CAP
    log_es = [d["evidence"]["log_e"] for d in out["opened"]]
    assert log_es == sorted(log_es, reverse=True)


def test_folklore_features_need_seven_days() -> None:
    rows = [r for r in strong_rows() if r["day"] <= day(5)]
    for r in rows:
        r["features"]["reentry_after_stop"] = r["features"]["danger4"]
    record = feat.group_record(rows, "reentry_after_stop", "all")
    assert record["days"] == 6 and record["flagged_losers"] >= 10
    assert all(d["group"]["feature"] != "reentry_after_stop"
               for d in feat.weekly_lessons(rows, features=("reentry_after_stop",), q=1.0)["opened"])


@pytest.mark.parametrize("source, split", [("history", "confirm"), ("history", "val"), ("history", "test"),
                                           ("history", "final_val"), ("history", "final_test"),
                                           ("history", "final_train"), ("history", None), ("exam", "confirm")])
def test_the_miner_refuses_every_split_but_train(source: str, split: str | None) -> None:
    rows = coins(random.Random(1), 3, 25)
    rows[7] = {**rows[7], "source": source, "split": split}
    with pytest.raises(feat.SplitLocked):
        feat.weekly_lessons(rows, features=("noise",))


def test_train_history_and_forward_rows_may_be_mined() -> None:
    rows = coins(random.Random(1), 3, 25)
    rows += [{**r, "source": "history", "split": "train", "mint": "H" + r["mint"]} for r in rows[:30]]
    feat.check_lesson_rows(rows)
    assert feat.weekly_lessons(rows, features=("noise",))["examined"] >= 1


def test_lesson_code_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    banned_imports = {"os", "sqlite3", "shutil", "subprocess", "socket", "tempfile", "io", "requests"}
    banned_calls = {"open", "write_text", "write_bytes", "unlink", "mkdir", "rename", "touch", "rmdir", "chmod"}
    for path in sorted(EXPERIENCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & banned_imports, path.name
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in banned_imports, path.name
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                assert name not in banned_calls, f"{path.name} calls {name}"
    real_open = builtins.open

    def guarded(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        assert not set(mode) & set("wax+"), f"lesson code opened {file} for writing"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.chdir(tmp_path)
    out = feat.weekly_lessons(strong_rows(), features=("danger4", "noise"))
    assert out["opened"] and list(tmp_path.iterdir()) == []
