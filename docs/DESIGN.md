# nightcrawler - design and contracts

An honest, provable version of the viral "crawler + AI judge + bots" memecoin
bot. It runs in **paper mode** by default: simulated fills are priced from the
**same live Jupiter Ultra quote** that live mode would execute, with the same
fees. Every decision and fill is written to a **sha256 hash chain before any
later price is known**, so results cannot be edited with hindsight.

This file is the contract for the implementers. Each module's docstrings are
the detailed spec; this page ties them together.

> Honesty first: AI agents have shown no proven edge on memecoins, and any
> signal decays within weeks. The backtester and the dataset collector exist
> to *measure* honestly (no lookahead, no survivorship bias, pessimistic
> costs). A $100 bankroll with ~$20 positions pays ~2-5% per round trip in
> fees, impact and network costs - most setups will not beat that.

---

## 1. Module map

```
src/nightcrawler/
  __init__.py        version
  __main__.py        python -m nightcrawler -> cli.main
  config.py          Settings (frozen, from env), Secret, ConfigError, load_settings      [foundation]
  models.py          all shared dataclasses + units helpers                                [foundation]
  clock.py           Clock protocol, RealClock, FakeClock                                  [foundation]
  http.py            HttpClient: per-host token buckets, retries/backoff, HttpError        [foundation]
  hashing.py         canonical_json, receipt_hash, verify_receipts                         [foundation]
  base58.py          b58encode/b58decode/is_pubkey (no deps)                               [foundation]
  logging_setup.py   one-line logs + secret redaction filter                               [foundation]
  sources/
    __init__.py      Sources bundle + build_sources(settings, http)                        [foundation]
    _parse.py        to_float/to_int/to_bool/parse_ts/get_path/strip_gt_id/chunks          [foundation]
    dexscreener.py   DexScreenerClient, pair_to_snapshot                                   O1
    geckoterminal.py GeckoTerminalClient (pools, trades, ohlcv), normalize_pool            O1
    rugcheck.py      RugCheckClient, RugReport, parse_report (AMM exclusion)               O1
    jupiter.py       JupiterClient (Ultra order/execute/holdings/shield, tokens, prices)   O1
    solana_rpc.py    SolanaRpc (mint_info, balance, simulate, signature_status)            O1
  crawler.py         Crawler.poll()/refresh()/prefilter()                                  O2
  cocoon.py          Cocoon.check() -> SafetyReport (FAIL CLOSED)                          O2
  radar.py           Radar.scan() -> RadarSignal                                           O2
  strategy.py        PURE entry_signal / exit_signal / exit_levels                         O3
  backtest.py        Backtester (no lookahead), CostModel, sweep                           O3
  dataset.py         collect() unbiased multi-coin candles                                 O3
  judge.py           Judge.decide() via Anthropic API, build_features                      O4
  broker/base.py     Broker protocol + execution errors                                    O5
  broker/paper.py    PaperBroker (live quotes, virtual wallet)                             O5
  broker/live.py     LiveBroker (sign + Ultra execute)                                     O5
  broker/wallet.py   Wallet, load_keypair, generate_new                                    O5
  risk.py            RiskManager, size_position_usd                                        O5
  ledger.py          Ledger (SQLite WAL) + receipts                                        O6
  audit.py           Auditor.reconcile(), trade P&L                                        O6
  dashboard.py       read-only phone dashboard (stdlib http.server)                        O6
  engine.py          Engine.tick()/run_forever(), build_engine                             Integrator
  cli.py             `nightcrawler` console script                                         Integrator
```

Dependency direction (no cycles): `config, models, clock` <- `http, hashing,
logging_setup` <- `sources` <- `crawler, cocoon, radar` ; `strategy` depends
only on `models` ; `judge` on `models, config` ; `broker, risk` on `sources,
ledger(duck-typed), models` ; `engine` on everything ; `cli` on `engine` and the
tools. Modules receive collaborators through constructors (dependency
injection); nothing creates its own `HttpClient` or reads `os.environ`
except `config.load_settings` and `engine.build_engine`.

## 2. Ownership (next phase)

Each owner edits ONLY their files + their own tests. Foundation files are
frozen; if a contract needs to change, tell the integrator instead of editing.

| Owner | Files | Tests |
|-------|-------|-------|
| O1 sources | `src/nightcrawler/sources/{dexscreener,geckoterminal,rugcheck,jupiter,solana_rpc}.py` | `tests/test_sources_*.py` |
| O2 discovery+safety | `crawler.py`, `cocoon.py`, `radar.py` | `tests/test_crawler.py`, `test_cocoon.py`, `test_radar.py` |
| O3 strategy+backtest | `strategy.py`, `backtest.py`, `dataset.py` | `tests/test_strategy.py`, `test_backtest.py`, `test_dataset.py` |
| O4 judge | `judge.py` | `tests/test_judge.py` |
| O5 execution+risk | `broker/{base,paper,live,wallet}.py`, `risk.py` | `tests/test_broker_paper.py`, `test_broker_live.py`, `test_wallet.py`, `test_risk.py` |
| O6 records+ops | `ledger.py`, `audit.py`, `dashboard.py`, `Dockerfile`, `.dockerignore`, `railway.json`, `.env.example`, `.gitignore` | `tests/test_ledger.py`, `test_audit.py`, `test_dashboard.py` |
| Integrator (later) | `engine.py`, `cli.py`, `README.md`, `docs/GOING_LIVE.md`, `docs/RAILWAY.md` | `tests/test_engine.py`, `test_cli.py`, e2e |
| Architect (done) | `pyproject.toml`, `__init__.py`, `__main__.py`, `config.py`, `models.py`, `clock.py`, `http.py`, `hashing.py`, `base58.py`, `logging_setup.py`, `sources/__init__.py`, `sources/_parse.py`, `tests/{conftest,fakes}.py`, `tests/fixtures/`, `data/samples/`, `docs/DESIGN.md` | `tests/test_{config,http,models,hashing,parse,foundation_misc,contract}.py` |

Every stub raises `NotImplementedError`; constructors already store their
dependencies so wiring can be tested early. Keep the public names and
signatures; you may add private helpers and extra optional keyword arguments.

## 3. Units conventions (also in `models.py`)

| Quantity | Type / unit | Field naming |
|----------|-------------|--------------|
| timestamps | `float` epoch seconds UTC | `ts`, `*_at` |
| candle open time | `int` epoch seconds (interval START) | `Candle.ts` |
| durations | as named | `*_s`, `*_min`, `*_h`, `latency_ms` |
| SOL in state/ledger | `int` lamports (1e9 per SOL) | `*_lamports` |
| SOL in settings/display | `float` SOL | `sol_reserve`, `network_fee_sol` |
| token amounts | `int` base units + `token_decimals` | `token_amount` |
| USD | `float` dollars | `*_usd`, `price_usd` (per WHOLE token), `sol_usd` (per SOL) |
| model/data ratios | `float` PERCENT (5.0 = 5 %) | `*_pct`, `price_change_*` |
| price impact | PERCENT, non-negative magnitude of ADVERSE impact | `price_impact_pct` |
| fees | `int` basis points | `*_bps` |
| confidences / fractions | `float` in [0, 1] | `confidence`, `fraction` |
| strategy/risk knobs (Settings) | FRACTIONS (0.20 = 20 %) | `POSITION_PCT, DAILY_LOSS_LIMIT_PCT, MAX_DRAWDOWN_HALT_PCT, DIP_PCT, TAKE_PROFIT_PCT, TRAIL_PCT, STOP_LOSS_PCT` |
| filter thresholds (Settings) | PERCENT | `MAX_PRICE_IMPACT_PCT, COCOON_*_PCT, RADAR_*_PCT` |

`config.py` validates ranges per family (a fraction above 1 or a percent of
0 fails at startup with a hint). Risk limits (daily loss, drawdown) are
measured in **SOL** (lamports), not USD, so a SOL/USD move alone cannot halt
the bot; the dashboard shows both.

Jupiter sign gotcha (verified live 2026-10-08): Ultra `/order` reports adverse
impact as a NEGATIVE fraction string (`priceImpactPct: "-0.0219"` when
`outUsdValue` is 2.2 % below `inUsdValue`). `Quote.price_impact_pct` stores
`abs(fraction) * 100`. `Quote.usd_value_loss_pct` gives the all-in loss.

## 4. Engine data flow

```
            every DISCOVERY_INTERVAL_S (30 s)
 Jupiter recent+trending ─┐
 GT new_pools p1-2 ───────┼─> Crawler.poll ──(prefilter)──> new TokenCandidates
 DexScreener boosts ──────┘   (paid_promo flag only)              │  <= 5 per tick
   too young (< MIN_AGE_MIN)? -> nursery; re-checked with a DexScreener batch once mature
                                                                   v
                                     Cocoon.check (RugCheck report, RPC mint, Jupiter Shield)
                                         │ fail -> Decision reject_cocoon ──> receipt
                                         v pass
                                     watchlist (<= 15, TTL 6 h) + Decision watch ──> receipt

            every WATCH_INTERVAL_S (60 s)
 DexScreener /tokens/v1 batch ──> MarketSnapshot per watched mint (expire out-of-window ones)
 GT ohlcv 1m (~180 min, <= 3 tokens/tick) ──> strategy.entry_signal (closed candles only)
     enter? ──> Radar.scan (GT trades >= $300)        flagged/error -> reject_radar
            ──> Judge.decide(build_features)          required & "no" -> reject_judge
            ──> RiskManager.can_open + size_position  -> reject_risk
            ──> broker.quote("buy")                   -> reject_quote (impact/error)
            ──> Decision enter ──> RECEIPT (before execution)
            ──> broker.execute ──> Fill ──> RECEIPT ──> Position upsert

            every POSITION_INTERVAL_S (10 s)
 Jupiter price v3 (batched) ──> mark positions (peak/last price)
 (every RADAR_INTERVAL_S) Radar.scan open positions
     strategy.exit_signal ──> quote("sell", fraction) ──> Decision exit|exit_partial ──> RECEIPT
                          ──> broker.execute ──> Fill ──> RECEIPT ──> Position update/close

            every tick: kill switch (env KILL_SWITCH or DATA_DIR/KILL): stop | sell_all
            every EQUITY_INTERVAL_S: EquityPoint -> ledger (risk limits + dashboard curve)
```

Rules: each stage is wrapped in try/except (log + `error` receipt + kv
`engine.last_error`), so the loop never dies. A swap is never retried
blindly: failed or unknown outcomes are reconciled and re-quoted.

## 5. Receipts (hindsight-proof hash chain)

```
body = canonical_json({"seq": seq, "ts": ts, "kind": kind, "payload": payload})
hash = sha256_hex(prev_hash + body)
canonical_json(x) = json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)
```

* `seq` starts at 1, +1 each; `prev_hash` of seq 1 = 64 zeros (`GENESIS_HASH`).
* `ts` = epoch seconds rounded to milliseconds.
* `payload` is normalized (`hashing.normalize_payload`) before hashing AND
  storing, so stored bytes == hashed bytes; NaN/inf are rejected.
* Kinds: `boot` (version, mode, public settings), `decision`
  (`Decision.to_dict()`), `fill` (`Fill.to_dict()`), `swap_failed`, `error`,
  `kill`, `halt`, `reset`, `note`.
* Ordering guarantee: the engine appends the `decision` receipt before
  executing, and the `fill` receipt immediately after, before fetching any
  newer price.
* `Ledger.head()` -> `(seq, hash)` is shown on the dashboard and by
  `nightcrawler receipts head`; `nightcrawler receipts verify` re-walks the
  chain (`hashing.verify_receipts`); `receipts export PATH` writes JSONL that
  anyone can verify with ~10 lines of code in any language.
* Publishing the head hash (e.g. posting it somewhere public) commits to the
  entire history up to that point.

## 6. Rate budgets (shared `HttpClient`, one token bucket per host)

| Host | Bucket (rate, burst) | Planned use per minute |
|------|----------------------|------------------------|
| `api.geckoterminal.com` | 20/min, burst 2 (free tier ~30/min, shared IP 429s) | crawler 4 (new_pools p1-2 x2), candles <= 3, radar <= 2-4, dataset collector when run alone |
| `api.rugcheck.xyz` | 1/s, burst 1 | cocoon <= 10 (5 per discovery tick) |
| `lite-api.jup.ag` / `api.jup.ag` | 1/s, burst 1 | crawler 4, price v3 6, shield <= 10, quotes on demand |
| `api.dexscreener.com` | 60/min, burst 3 | crawler 4, refresh 1 (30 mints per call) |
| Solana RPC (`SOLANA_RPC_URL` host) | 5/s, burst 5 | cocoon mint_info, live simulate/status |
| anything else | 5/s, burst 5 | - |

Retries: 429/5xx/connection errors, max 4, exponential backoff with jitter,
`Retry-After` honoured (capped 60 s). Ultra `/execute` is sent with
`retry=False`. All sleeps go through the injected `Clock`.

## 7. Failure policy (fail closed)

* Cocoon: a required source down -> `passed=False`, reason
  `source unavailable: X`.
* Radar error at entry -> reject; radar error on an open position -> ignored.
* Judge error/refusal/timeout/budget -> Verdict `no` (`source="error"`).
* Quote with impact > `MAX_PRICE_IMPACT_PCT` or an unexpected Ultra error -> no trade.
* Live: missing transaction, simulation error -> no send. Unknown outcome -> reconcile before acting.
* Kill file unreadable/garbled -> `stop`.
* Config invalid -> process refuses to start (exit code 3).

## 8. Paper == live (only sign + send differ)

Both brokers quote with Jupiter Ultra `/order` at the exact size; paper fills
at `quote.out_amount` (already net of pool fees and the 0.1 % Ultra fee),
deducts `NETWORK_FEE_SOL` per swap, reserves token-account rent
(2,039,280 lamports) on a first buy and refunds it on a full exit. Live signs
the returned transaction, optionally simulates it, sends it via Ultra
`/execute`, and records the ACTUAL in/out amounts (with the quote's
`out_amount` kept as `expected_out_amount` to measure slippage).

## 9. Ledger kv keys (JSON values)

`paper.sol_lamports`, `paper.tokens` {mint:int}, `paper.rent` {mint:int},
`paper.start_lamports`, `paper.start_sol_usd`, `live.start_lamports`,
`risk.halted` {halted, reason, ts}, `risk.peak_reset_ts`, `engine.heartbeat`,
`engine.started_at`, `engine.status`, `engine.kill_mode`, `engine.last_error`,
`judge.cost_usd_total`, `judge.cost_usd_day` {day, usd}, `judge.calls`,
`wallet.pubkey`. The dashboard reads ONLY the ledger (no network calls).

## 10. Settings

All settings, defaults, units and help texts live in `config.Settings` field
metadata (`Settings.describe()`); `.env.example` is generated from it and a
test checks it lists every setting. Beyond the owner's list the architect
added: `LOG_LEVEL`, `SIMULATE_BEFORE_SEND`, `QUOTE_MAX_AGE_S`,
`MIN_ORGANIC_SCORE`, `DIP_LOOKBACK_H`, `CANDLE_WINDOW_MIN`, `WATCHLIST_MAX`,
`WATCHLIST_TTL_H`, `COCOON_*` thresholds, `RADAR_*` thresholds,
`JUDGE_MAX_DAILY_USD`, `DASHBOARD_HOST`, `EQUITY_INTERVAL_S`.

## 11. Testing conventions

* `pytest -q` is fully OFFLINE: `conftest.py` blocks `requests` network calls
  in every test not marked `@pytest.mark.live`; live tests run only with
  `NIGHTCRAWLER_LIVE_TESTS=1`.
* HTTP: use the real `HttpClient` over `fakes.FakeHttp` (fixture
  `http_client`), with routes registered from `tests/fixtures/*.json`
  (`fake_http.register_fixture("/ultra/v1/order", "jup_ultra_order_buy")`).
  Pattern = substring of the full URL incl. query (`re:` prefix for regex);
  the most recently registered route wins (`times=1` for one-shot failures).
* Time: `fake_clock` (FakeClock at 2026-10-08T16:00:00Z); never `time.time()`.
* Settings: `make_settings(**overrides)` (attr or ENV names), `settings`,
  `tmp_data_dir`.
* Fixtures are documented in `tests/fixtures/README.md` (synthetic ones are
  labelled). Backtest samples: `data/samples/higgs_1m.json`,
  `data/samples/hooki_1m.json` (the HOOKI 2026-10-06 00:31 UTC partial candle
  was re-fetched and patched; see its `patches` key).

## 12. Per-owner acceptance checklist

* **O1**: every client method parses its fixture; missing fields never raise;
  HTTP errors surface as `HttpError`/`ReportUnavailable`/`RpcError`;
  `quote_from_order` handles all three Ultra order fixtures (incl. negative
  impact and "Insufficient funds"); `parse_report` excludes the pool account
  in `rugcheck_report.json` (top-10 must NOT count `2uZuTQ...` / the curve).
* **O2**: crawler merges feeds and dedupes with TTL; prefilter reasons;
  cocoon passes the clean fixture and fails the risky one with the right rule
  ids; any source failure fails closed; radar flags creator/insider sells.
* **O3**: strategy is pure and uses closed candles only; tests prove no
  lookahead (appending future candles never changes a past decision);
  backtest pessimistic intrabar ordering; HIGGS/HOOKI samples run end to end;
  sweep reports out-of-sample metrics.
* **O4**: exact request shape (assert on the fake client's kwargs), refusal
  first, fail closed on every error class, caching, budget, cost estimate.
* **O5**: paper fill == quote out_amount, fees and rent exact, impact/stale
  rejection, restart resumes balances; live refuses without confirmation /
  wallet / solders and never retries `/execute`; wallet never prints secrets;
  risk rules in documented order.
* **O6**: chain append/verify/tamper detection/export; thread-safety under
  concurrent readers; audit drift detection; dashboard routes, auth, schema,
  no secrets in HTML/JSON.
