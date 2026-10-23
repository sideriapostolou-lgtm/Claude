import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
OUT = (
    Path(sys.argv[2]).resolve()
    if len(sys.argv) > 2
    else Path(__file__).resolve().parent
)
checks = []
sources = {}


def read(p):
    b = (ROOT / p).read_bytes()
    sources[p] = hashlib.sha256(b).hexdigest()
    return json.loads(b)


def check(name, value):
    checks.append({"name": name, "pass": bool(value)})
    assert value, name


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def rows(p):
    return read(p)["response"]["deploy"]


def events(rs, typ):
    return [
        json.loads(r["message"].split(typ + " ", 1)[1])
        for r in rs
        if typ + " {" in r["message"]
    ]


base = "research/daily_status_2026-10-18/"
rr = rows(base + "DAY_REAL_LOGS.json")
pp = rows(base + "DAY_PRACTICE_LOGS.json")
real = events(rr, "speeddesk_live_settlement")
practice = events(pp, "speeddesk_twin_settlement")
check("one real settlement", len(real) == 1)
check("zero real fill rows", len(events(rr, "speeddesk_live_fill")) == 0)
check("36 practice settlement rows", len(practice) == 36)
check("zero practice fill rows", not any("speeddesk_fill " in x["message"] for x in pp))
check("36 distinct practice windows", len({s["window"] for s in practice}) == 36)
nonempty = [s for s in practice if s["up_shares"] + s["down_shares"] > 0]
check("1 nonempty practice settlement", len(nonempty) == 1)
check("35 empty practice settlements", len(practice) - len(nonempty) == 35)
for i, s in enumerate(real + practice):
    check(
        f"settlement {i} payout-cost-fee",
        near(s["payout_usd"] - s["cost_usd"] - s["fee_usd"], s["pnl_usd"]),
    )
    check(
        f"settlement {i} decomposition",
        near(s["locked_usd"] + s["direction_usd"], s["pnl_usd"]),
    )
check("real net +0.0127", near(sum(s["pnl_usd"] for s in real), 0.0127))
check("practice net +0.59", near(sum(s["pnl_usd"] for s in practice), 0.59))
check(
    "payout split no duplicate credit",
    near(
        real[0]["paired_credit_usd"] + real[0]["net_payout_usd"], real[0]["payout_usd"]
    ),
)
old = rows("research/daily_status_2026-10-17/DAY_MONEY_LOGS.json")
fills = events(old, "speeddesk_live_fill")
carry = [f for f in fills if f["window"] == real[0]["window"]]
check("inherited two actual fills", len(carry) == 2)
check("inherited cost .97", near(sum(f["price"] * f["size"] for f in carry), 0.97))
check("inherited fees .0173", near(sum(f["fee_usd"] for f in carry), 0.0173))
check("carry fills predate Oct17", all(f["at"] < 1792195200 for f in carry))
check(
    "all returned settlement logs Oct17",
    all(r["timestamp"].startswith("2026-10-17") for r in rr + pp),
)
native = read("research/daily_status_2026-10-17/LAST_NATIVE.json")["state"]
check(
    "caps unchanged last native",
    native["caps"]
    == {
        "window_usd": 20,
        "open_usd": 40,
        "day_stop_usd": 12,
        "clip": 5,
        "total_stop_usd": 10,
    },
)
check(
    "policy reduction only",
    native["pair_execution"]["policy"] == "reduction_only"
    and native["pair_execution"]["starter"] == "disabled"
    and not native["pair_execution"]["automatic_resume"],
)
check("no practice comparability", not native["pair_execution"]["practice_comparable"])
check(
    "stale coverage 26/36 complete 10 gaps",
    native["today"]["scorecard"]["eligible_windows"] == 36
    and native["today"]["scorecard"]["complete_windows"] == 26
    and native["today"]["scorecard"]["gap_windows"] == 10,
)
check("no full day certification", not native["today"]["scorecard"]["day_complete"])
check(
    "ladder no pending promotion",
    native["ladder"]["rung"] == 0
    and native["ladder"]["top_rung"] == 0
    and not native["ladder"]["promotion"]["ready"]
    and not native["ladder"]["change_pending"],
)
check(
    "ladder blockers retained",
    set(native["ladder"]["promotion"]["blocked"])
    == {"at_ceiling", "windows", "gain", "stops"},
)
check("zero later status rows", not rows(base + "NO_LATER_NATIVE.json"))
summary = {
    "scope": "offline selected sanitized receipts; no venue read or new full-day coverage certificate",
    "checks_passed": len(checks),
    "checks": checks,
    "source_sha256": sources,
    "real_pnl_usd": sum(s["pnl_usd"] for s in real),
    "practice_pnl_usd": sum(s["pnl_usd"] for s in practice),
    "practice_first_log": pp[0]["timestamp"],
    "practice_last_log": pp[-1]["timestamp"],
    "current_balance_and_exposure": "unknown; last-native snapshot predates halt",
}
(OUT / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
print(
    json.dumps(
        {k: v for k, v in summary.items() if k not in ["checks", "source_sha256"]},
        indent=2,
    )
)
