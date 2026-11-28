"""Synthetic metadata only; no market data or held-out outcomes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("shadow_sufficiency", Path(__file__).with_name("shadow_sufficiency.py"))
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_zero_completed_windows_cannot_be_profit_evidence() -> None:
    report = module.assess({"town": {"windows": 0, "void_windows": 60},
                            "feed": {"dropped": 1450000, "late": 0}}, {}, {})
    assert report["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert report["arena"]["lifetime_coverage_share"] == 0
    assert not report["ready_for_comparison"] and not report["profitability_established"]


def test_clean_metadata_alone_never_claims_complete_execution_evidence() -> None:
    report = module.assess({"town": {"windows": 1000, "void_windows": 0},
                            "feed": {"dropped": 0, "late": 0}},
                           {"bytes_by_lane": {"spot": 250}, "status":
                            {"read_only": True, "order_capability": False, "storage_level": 0}},
                           {"ok": True, "mismatched": [], "segments": 1})
    assert report["verdict"] == "METADATA_CHECKS_ONLY"
    assert not report["ready_for_comparison"] and not report["profitability_established"]


@pytest.mark.parametrize("value", [None, True, False, "0", -1, float("inf"), float("nan")])
def test_unknown_or_invalid_is_not_zero(value: object) -> None:
    assert module.number(value) is None


def test_unrequested_fields_are_never_echoed() -> None:
    report = module.assess({"not_a_metadata_field": "unrelated-value"}, {}, {})
    assert "unrelated-value" not in str(report)


def test_raw_tape_array_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    path.write_text('[{"price": 0.5}]', encoding="utf-8")
    with pytest.raises(TypeError, match="metadata object"):
        module.read_metadata(path)


def test_oversize_metadata_is_rejected_before_read(tmp_path: Path) -> None:
    path = tmp_path / "too_large.json"
    path.write_bytes(b" " * (module.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="256 KiB"):
        module.read_metadata(path)
