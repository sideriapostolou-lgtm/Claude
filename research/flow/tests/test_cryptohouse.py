"""Client behaviour without network: JSONCompact parsing, error mapping, budget, retries."""
import json

import pytest

import cryptohouse as C


def test_json_compact_types():
    doc = {"meta": [{"name": "a", "type": "UInt64"}, {"name": "b", "type": "Array(Tuple(String, UInt64, Float32))"},
                    {"name": "c", "type": "Nullable(Int64)"}, {"name": "d", "type": "Float64"}],
           "data": [["18446744073709551615", [["x", "5", 1.5]], None, "nan"]],
           "statistics": {"elapsed": 0.5, "rows_read": 10, "bytes_read": 20}}
    cols, types, rows, st = C.parse_json_compact(json.dumps(doc))
    assert cols == ["a", "b", "c", "d"]
    assert rows[0][0] == 2 ** 64 - 1
    assert rows[0][1] == [["x", 5, 1.5]]
    assert rows[0][2] is None
    assert rows[0][3] != rows[0][3]   # nan
    assert st["rows_read"] == 10


def test_error_mapping():
    q = C.parse_error(500, {"X-ClickHouse-Exception-Code": "201"},
                      "Code: 201. DB::Exception: Quota for user `crypto` for 3600s has been exceeded: queries = 121/120. "
                      "Interval will end at 2026-10-08 21:00:00. (QUOTA_EXCEEDED)", now=1791490000)
    assert isinstance(q, C.QuotaExceeded) and q.reset_at == 1791493200
    q2 = C.parse_error(500, {}, "Code: 201. ... (QUOTA_EXCEEDED)", now=1791490000)
    assert isinstance(q2, C.QuotaExceeded) and q2.reset_at == 1791493200   # top of next hour
    assert isinstance(C.parse_error(408, {"X-ClickHouse-Exception-Code": "159"}, "TIMEOUT_EXCEEDED"), C.QueryTimeout)
    assert isinstance(C.parse_error(500, {}, "Code: 396. Limit for result exceeded (TOO_MANY_ROWS_OR_BYTES)"), C.ResultTooLarge)
    assert isinstance(C.parse_error(502, {}, "bad gateway"), C.TransientError)
    assert type(C.parse_error(400, {}, "Code: 62. Syntax error")) is C.CHError


class FakeClock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, d):
        self.slept.append(d)
        self.t += d


def test_budget_waits_when_hour_is_full(tmp_path):
    clk = FakeClock()
    qlog = C.QueryLog(tmp_path / "log.jsonl")
    for i in range(5):
        qlog.append({"ts": clk.t - 3000 + i, "elapsed_s": 1.0, "wall_s": 1.0})
    ch = C.CryptoHouse(log_path=tmp_path / "log.jsonl", budget=C.Budget(max_per_hour=5, min_gap_s=0),
                       sleep=clk.sleep, clock=clk)
    slept = ch.wait_for_budget()
    # the oldest of the 5 queries (t-3000) leaves the window after ~600 s
    assert 590 <= slept <= 610


def test_budget_respects_exec_seconds(tmp_path):
    clk = FakeClock()
    qlog = C.QueryLog(tmp_path / "log.jsonl")
    qlog.append({"ts": clk.t - 1800, "elapsed_s": 100.0})
    ch = C.CryptoHouse(log_path=tmp_path / "log.jsonl", budget=C.Budget(max_per_hour=90, max_exec_s_per_hour=50, min_gap_s=0),
                       sleep=clk.sleep, clock=clk)
    assert ch.wait_for_budget() == pytest.approx(1801, abs=2)


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self.text = body
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _ok_body():
    return json.dumps({"meta": [{"name": "x", "type": "UInt64"}], "data": [["7"]], "rows": 1,
                       "statistics": {"elapsed": 0.25, "rows_read": 100, "bytes_read": 1000}})


def test_query_logs_and_retries_transient(tmp_path):
    import requests
    clk = FakeClock()
    sess = FakeSession([requests.ConnectionError("reset"), FakeResp(200, _ok_body(), {"X-ClickHouse-Query-Id": "q1"})])
    ch = C.CryptoHouse(log_path=tmp_path / "log.jsonl", budget=C.Budget(min_gap_s=0), session=sess,
                       sleep=clk.sleep, clock=clk)
    r = ch.query("SELECT 7", tag="t")
    assert r.rows == [[7]] and r.rows_read == 100
    es = ch.qlog.entries()
    assert len(es) == 2 and es[0]["error"] == "ConnectionError" and es[1]["result_rows"] == 1
    assert clk.slept and clk.slept[0] == 5.0


def test_query_waits_on_quota_then_succeeds(tmp_path):
    clk = FakeClock(1_800_000_100.0)
    quota = FakeResp(500, "Code: 201. Interval will end at 2027-01-15 08:00:00. (QUOTA_EXCEEDED)",
                     {"X-ClickHouse-Exception-Code": "201"})
    sess = FakeSession([quota, FakeResp(200, _ok_body())])
    ch = C.CryptoHouse(log_path=tmp_path / "log.jsonl", budget=C.Budget(min_gap_s=0), session=sess,
                       sleep=clk.sleep, clock=clk)
    r = ch.query("SELECT 7")
    assert r.rows == [[7]]
    assert clk.t >= ch.server_reset_at


def test_timeout_is_raised_for_caller_to_split(tmp_path):
    sess = FakeSession([FakeResp(408, "Code: 159. TIMEOUT_EXCEEDED", {"X-ClickHouse-Exception-Code": "159"})])
    clk = FakeClock()
    ch = C.CryptoHouse(log_path=tmp_path / "log.jsonl", budget=C.Budget(min_gap_s=0), session=sess,
                       sleep=clk.sleep, clock=clk)
    with pytest.raises(C.QueryTimeout):
        ch.query("SELECT 1")
    assert ch.qlog.entries()[0]["error"] == "QueryTimeout"


def test_summarize_log(tmp_path):
    q = C.QueryLog(tmp_path / "l.jsonl")
    q.append({"ts": 1, "tag": "curve:x", "elapsed_s": 10, "rows_read": 5})
    q.append({"ts": 2, "tag": "b2:y", "elapsed_s": 20, "rows_read": 5, "error": "QueryTimeout"})
    s = C.summarize_log(tmp_path / "l.jsonl")
    assert s["queries"] == 2 and s["errors"] == {"QueryTimeout": 1} and s["by_tag"]["curve"]["n"] == 1
