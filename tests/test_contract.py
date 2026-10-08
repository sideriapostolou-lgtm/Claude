"""Contract tests: every module imports, exports what it promises, and shared data is sane."""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from pathlib import Path

import pytest

import nightcrawler
from nightcrawler.cli import EXIT_CONFIG, EXIT_OK, build_parser, main
from nightcrawler.models import Candle

ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted(m.name for m in pkgutil.walk_packages(nightcrawler.__path__, "nightcrawler."))

EXPECTED_PUBLIC = {
    "nightcrawler.sources.dexscreener": ["DexScreenerClient", "pair_to_snapshot"],
    "nightcrawler.sources.geckoterminal": ["GeckoTerminalClient", "normalize_pool", "pool_to_candidate"],
    "nightcrawler.sources.rugcheck": ["RugCheckClient", "RugReport", "parse_report", "ReportUnavailable"],
    "nightcrawler.sources.jupiter": ["JupiterClient", "quote_from_order", "token_to_candidate"],
    "nightcrawler.sources.solana_rpc": ["SolanaRpc", "RpcError"],
    "nightcrawler.sources": ["Sources", "build_sources"],
    "nightcrawler.crawler": ["Crawler"],
    "nightcrawler.cocoon": ["Cocoon", "DANGEROUS_EXTENSIONS"],
    "nightcrawler.radar": ["Radar"],
    "nightcrawler.strategy": ["entry_signal", "exit_signal", "exit_levels", "closed_candles"],
    "nightcrawler.judge": ["Judge", "STATIC_SYSTEM_PROMPT", "VERDICT_SCHEMA", "estimate_cost_usd", "build_features"],
    "nightcrawler.broker.base": ["Broker", "QuoteRejected", "SwapFailed", "SwapUnknown"],
    "nightcrawler.broker.paper": ["PaperBroker"],
    "nightcrawler.broker.live": ["LiveBroker"],
    "nightcrawler.broker.wallet": ["Wallet", "load_keypair", "generate_new"],
    "nightcrawler.risk": ["RiskManager", "size_position_usd"],
    "nightcrawler.ledger": ["Ledger"],
    "nightcrawler.audit": ["Auditor", "AuditReport"],
    "nightcrawler.engine": ["Engine", "build_engine"],
    "nightcrawler.backtest": ["Backtester", "CostModel", "load_series"],
    "nightcrawler.dataset": ["collect"],
    "nightcrawler.dashboard": ["DashboardServer", "build_state", "render_html"],
    "nightcrawler.cli": ["main", "build_parser"],
}


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_and_all_is_valid(name: str) -> None:
    mod = importlib.import_module(name)
    for attr in getattr(mod, "__all__", []):
        assert hasattr(mod, attr), f"{name}.__all__ lists missing {attr}"


@pytest.mark.parametrize("name,attrs", sorted(EXPECTED_PUBLIC.items()))
def test_expected_public_api(name: str, attrs: list[str]) -> None:
    mod = importlib.import_module(name)
    for attr in attrs:
        obj = getattr(mod, attr)
        assert obj is not None
        if inspect.isfunction(obj) or inspect.isclass(obj):
            assert obj.__doc__, f"{name}.{attr} needs a docstring (it is the contract)"


def test_judge_contract_constants() -> None:
    from nightcrawler.judge import PRICE_TABLE, STATIC_SYSTEM_PROMPT, VERDICT_SCHEMA, uses_fallbacks

    assert VERDICT_SCHEMA["required"] == ["decision", "confidence", "reasons"]
    assert VERDICT_SCHEMA["additionalProperties"] is False
    assert PRICE_TABLE["claude-opus-5-5"] == (4.0, 20.0, 0.20)
    assert uses_fallbacks("claude-opus-5-5") and uses_fallbacks("claude-fable-5-1")
    assert uses_fallbacks("claude-sonnet-5-5") and not uses_fallbacks("claude-haiku-5-5")
    assert "{" not in STATIC_SYSTEM_PROMPT and "202" not in STATIC_SYSTEM_PROMPT  # no templating / dates


@pytest.mark.parametrize("fname", ["higgs_1m.json", "hooki_1m.json"])
def test_backtest_samples_are_well_formed(fname: str) -> None:
    data = json.loads((ROOT / "data" / "samples" / fname).read_text())
    assert {"coin", "mint", "pool", "supply", "candles"} <= set(data)
    candles = [Candle.from_row(r) for r in data["candles"]]
    assert len(candles) > 1000
    ts = [c.ts for c in candles]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)
    assert all(t % 60 == 0 for t in ts)
    for c in candles:
        assert 0 < c.l <= min(c.o, c.c) + 1e-18 and c.h + 1e-18 >= max(c.o, c.c) and c.v >= 0


def test_hooki_partial_candle_was_patched() -> None:
    data = json.loads((ROOT / "data" / "samples" / "hooki_1m.json").read_text())
    row = next(r for r in data["candles"] if r[0] == 1791246660)  # 2026-10-06 00:31 UTC
    assert row[4] * data["supply"] == pytest.approx(459_327, rel=1e-4)  # true close mcap
    assert row[5] == pytest.approx(364.9, rel=1e-3)  # true volume
    nxt = next(r for r in data["candles"] if r[0] == 1791246720)
    assert nxt[1] == pytest.approx(row[4])  # next open == patched close
    assert data["patches"][0]["ts"] == 1791246660


def test_cli_parser_and_config_command(capsys, tmp_path: Path, monkeypatch) -> None:
    parser = build_parser()
    args = parser.parse_args(["receipts", "export", "out.jsonl"])
    assert args.command == "receipts" and args.receipts_cmd == "export" and args.path == "out.jsonl"
    args = parser.parse_args(["backtest", "data/samples", "--sweep", "--json", "o.json"])
    assert args.sweep and args.json_out == "o.json"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-print")
    assert main(["--env-file", str(tmp_path / "none.env"), "config", "--json"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "sk-ant-should-not-print" not in out
    data = json.loads(out)
    assert data["anthropic_api_key_set"] is True and data["trading_mode"] == "paper"
    monkeypatch.setenv("POSITION_PCT", "20")
    assert main(["--env-file", str(tmp_path / "none.env"), "config"]) == EXIT_CONFIG


def test_repo_files_exist() -> None:
    for rel in ["pyproject.toml", "Dockerfile", ".dockerignore", "railway.json", ".env.example", ".gitignore",
                "docs/DESIGN.md", "tests/fixtures/README.md"]:
        assert (ROOT / rel).is_file(), rel
