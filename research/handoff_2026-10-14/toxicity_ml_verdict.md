# toxicity_ml_verdict (workflow wf_31c62455-12c)



---
## result 0 

{"manifest_path":"/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_toxicity/data/manifest.json","note":"This is the manifest with three parts shortened: the per-file download hashes (see out/check_sources.json), the lagged-variant label stats (see out/dataset/lagged_build.json) and the per-feature NaN shares. The full manifest is on disk at manifest_path.","name":"kalshi_toxicity/data v1: sub-second resting-bid toxicity training set (KXBTC15M)","created_utc":"2026-10-13T20:35:13Z","lane_dir":"/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_toxicity/data","scope":"research only: public data, no orders, no keys, no Railway changes, no deploys, no pushes, nothing written under /home/user/Claude; downloads 25.1 MB, lane total 179 MB","files":{"main":{"TRAIN":{"path":".../kalshi_toxicity/data/out/dataset/main_train.parquet","rows":95015,"windows":70,"sha256":"b469cc73ee9c50fc7f757879ea61363114799093a7f3cbbe10d47589e67a425c"},"VAL":{"path":".../kalshi_toxicity/data/out/dataset/main_val.parquet","rows":31976,"windows":23,"sha256":"d734b1a539ad2e0ebf45fbcd57dc1e29d76ca1b6978beddc63231e074b4a5b6c"},"TEST":{"path":".../kalshi_toxicity/data/out/dataset/main_test.parquet","rows":31297,"windows":23,"sha256":"5e049a9fcea434b9fec173a348a407b6e074aebdf8c35acd3070d35986d9fbf6"},"build_log":".../kalshi_toxicity/data/out/dataset/main_build.json"},"lagged":{"TRAIN":{"path":".../kalshi_toxicity/data/out/dataset/lagged_train.parquet","rows":95026,"windows":70,"sha256":"9e65e58e3044dae23594ca1079d86ae4c928c565eab76d2787cfd9867bc71ec9"},"VAL":{"path":".../kalshi_toxicity/data/out/dataset/lagged_val.parquet","rows":31976,"windows":23,"sha256":"6552e29bb72460fb6f0d8e3ec78af452c70bb88ed8d3dadabe3d4f2467f333ea"},"TEST":{"path":".../kalshi_toxicity/data/out/dataset/lagged_test.parquet","rows":31299,"windows":23,"sha256":"8e8bc7acdbf62e5c46d6f7197206b7f66a8ba315ca57ab7b9fa563a4c1fe7fa1"},"build_log":".../kalshi_toxicity/data/out/dataset/lagged_build.json"},"split":{"path":".../kalshi_toxicity/data/out/dataset/split.json","sha256_file":"131b94fd8b1a40e333c1c5fe4e7b121f4fa6e1e8780319be33a9278789ebe215","sha256_windows":"f660f10de982aa233972297b9c081ba450309d77b7e49c044fc183372305902d"},"inventory":".../kalshi_toxicity/data/out/inventory.json","validate_live":".../kalshi_toxicity/data/out/validate_live.json","check_sources":".../kalshi_toxicity/data/out/check_sources.json","code_dir":".../kalshi_toxicity/data/code (inventory.py, pull_binance.py, pull_coinbase.py, ticks.py, features.py, build.py, validate_live.py, check_sources.py, make_manifest.py)","path_prefix":"... = /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad"},"load":"import pandas as pd; d = '/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_toxicity/data/out/dataset/'; tr = pd.read_parquet(d+'main_train.parquet'); va = pd.read_parquet(d+'main_val.parquet')  # main_test.parquet: open once, at the end","split":{"rule":"windows with >= 1 quotable unit in the lag-0 build, sorted by close; oldest 60 % TRAIN, next 20 % VAL, newest 20 % TEST; the lagged build reuses split.json","counts":{"TRAIN":70,"VAL":23,"TEST":23},"TRAIN":{"first":"KXBTC15M-26OCT120300-00","last":"KXBTC15M-26OCT122115-15","open_utc":"2026-10-12T06:45:00Z","close_utc":"2026-10-13T01:15:00Z","tickers":["KXBTC15M-26OCT120300-00","KXBTC15M-26OCT120315-15","KXBTC15M-26OCT120330-30","KXBTC15M-26OCT120345-45","KXBTC15M-26OCT120400-00","KXBTC15M-26OCT120415-15","KXBTC15M-26OCT120430-30","KXBTC15M-26OCT120445-45","KXBTC15M-26OCT120500-00","KXBTC15M-26OCT120515-15","KXBTC15M-26OCT120530-30","KXBTC15M-26OCT120545-45","KXBTC15M-26OCT120600-00","KXBTC15M-26OCT120615-15","KXBTC15M-26OCT120630-30","KXBTC15M-26OCT120745-45","KXBTC15M-26OCT120800-00","KXBTC15M-26OCT120815-15","KXBTC15M-26OCT120830-30","KXBTC15M-26OCT120845-45","KXBTC15M-26OCT120900-00","KXBTC15M-26OCT120915-15","KXBTC15M-26OCT120930-30","KXBTC15M-26OCT120945-45","KXBTC15M-26OCT121000-00","KXBTC15M-26OCT121015-15","KXBTC15M-26OCT121030-30","KXBTC15M-26OCT121045-45","KXBTC15M-26OCT121100-00","KXBTC15M-26OCT121115-15","KXBTC15M-26OCT121130-30","KXBTC15M-26OCT121145-45","KXBTC15M-26OCT121200-00","KXBTC15M-26OCT121215-15","KXBTC15M-26OCT121230-30","KXBTC15M-26OCT121245-45","KXBTC15M-26OCT121300-00","KXBTC15M-26OCT121315-15","KXBTC15M-26OCT121330-30","KXBTC15M-26OCT121345-45","KXBTC15M-26OCT121400-00","KXBTC15M-26OCT121415-15","KXBTC15M-26OCT121430-30","KXBTC15M-26OCT121445-45","KXBTC15M-26OCT121500-00","KXBTC15M-26OCT121515-15","KXBTC15M-26OCT121530-30","KXBTC15M-26OCT121545-45","KXBTC15M-26OCT121600-00","KXBTC15M-26OCT121615-15","KXBTC15M-26OCT121630-30","KXBTC15M-26OCT121645-45","KXBTC15M-26OCT121700-00","KXBTC15M-26OCT121715-15","KXBTC15M-26OCT121730-30","KXBTC15M-26OCT121745-45","KXBTC15M-26OCT121800-00","KXBTC15M-26OCT121815-15","KXBTC15M-26OCT121830-30","KXBTC15M-26OCT121845-45","KXBTC15M-26OCT121900-00","KXBTC15M-26OCT121915-15","KXBTC15M-26OCT121930-30","KXBTC15M-26OCT121945-45","KXBTC15M-26OCT122000-00","KXBTC15M-26OCT122015-15","KXBTC15M-26OCT122030-30","KXBTC15M-26OCT122045-45","KXBTC15M-26OCT122100-00","KXBTC15M-26OCT122115-15"]},"VAL":{"first":"KXBTC15M-26OCT122130-30","last":"KXBTC15M-26OCT130300-00","open_utc":"2026-10-13T01:15:00Z","close_utc":"2026-10-13T07:00:00Z","tickers":["KXBTC15M-26OCT122130-30","KXBTC15M-26OCT122145-45","KXBTC15M-26OCT122200-00","KXBTC15M-26OCT122215-15","KXBTC15M-26OCT122230-30","KXBTC15M-26OCT122245-45","KXBTC15M-26OCT122300-00","KXBTC15M-26OCT122315-15","KXBTC15M-26OCT122330-30","KXBTC15M-26OCT122345-45","KXBTC15M-26OCT130000-00","KXBTC15M-26OCT130015-15","KXBTC15M-26OCT130030-30","KXBTC15M-26OCT130045-45","KXBTC15M-26OCT130100-00","KXBTC15M-26OCT130115-15","KXBTC15M-26OCT130130-30","KXBTC15M-26OCT130145-45","KXBTC15M-26OCT130200-00","KXBTC15M-26OCT130215-15","KXBTC15M-26OCT130230-30","KXBTC15M-26OCT130245-45","KXBTC15M-26OCT130300-00"]},"TEST":{"first":"KXBTC15M-26OCT130315-15","last":"KXBTC15M-26OCT131245-45","open_utc":"2026-10-13T07:00:00Z","close_utc":"2026-10-13T16:45:00Z","tickers":["KXBTC15M-26OCT130315-15","KXBTC15M-26OCT130330-30","KXBTC15M-26OCT130345-45","KXBTC15M-26OCT130400-00","KXBTC15M-26OCT130415-15","KXBTC15M-26OCT130430-30","KXBTC15M-26OCT130500-00","KXBTC15M-26OCT130900-00","KXBTC15M-26OCT130915-15","KXBTC15M-26OCT130930-30","KXBTC15M-26OCT130945-45","KXBTC15M-26OCT131000-00","KXBTC15M-26OCT131015-15","KXBTC15M-26OCT131030-30","KXBTC15M-26OCT131045-45","KXBTC15M-26OCT131100-00","KXBTC15M-26OCT131115-15","KXBTC15M-26OCT131130-30","KXBTC15M-26OCT131145-45","KXBTC15M-26OCT131200-00","KXBTC15M-26OCT131215-15","KXBTC15M-26OCT131230-30","KXBTC15M-26OCT131245-45"]},"excluded_unquotable_windows":{"tickers":["KXBTC15M-26OCT120645-45","KXBTC15M-26OCT120700-00","KXBTC15M-26OCT120715-15","KXBTC15M-26OCT120730-30"],"why":"Coinbase traded in too few seconds: fewer than 1500 adjacent 1 s returns in the trailing hour, so the live bot's sigma and every unit are undefined; the live bot would not quote either"},"windows_without_tape_on_hand":{"count":16,"tickers":["KXBTC15M-26OCT130445-45","KXBTC15M-26OCT130515-15 .. KXBTC15M-26OCT130845-45 (15 windows)"],"note":"no Kalshi trade tape was on hand; not fetched, because this lane only downloaded Binance and Coinbase ticks"},"test_policy":"TEST rows are in their own files; no TEST label statistic was computed or looked at; use TEST once, at the end","cluster_unit":"window (column `window`; `window_idx` is the time order 0..115)"},"unit":{"key":["window","s","side"],"s":"integer unix decision second; f_left = close - s in [181, 899] (live rest orders were placed 182.7 .. 898.7 s before the close)","side":"1 = Up (YES bid), 0 = Down (NO bid); both sides every second","bid":"f_price = floor((fair_side - 0.03 + 1e-9)/0.01)*0.01, kept when 0 < price < 1 (speeddesk_model make_edge 0.03)","crosses_ask_proxy":"True when f_price >= the last taker-buy print price on that side before s. Rest orders are post_only, so such a bid would likely be refused. Primary set: crosses_ask_proxy == False (TRAIN excludes 21,306 rows, VAL 6,596). The rows stay in the files.","primary_rows":{"TRAIN":73709,"VAL":25380}},"fair":{"definition":"Replica of the live speeddesk_model fair: spot = last Coinbase BTC-USD trade with exchange time < s; strike = Kalshi floor_strike; sigma = RMS of log returns between adjacent Coinbase 1 s closes over the 3600 s ending at second s-1, needing >= 1500 returns; fair_up = Phi(ln(spot/K)/(sigma*sqrt(close-s)))","validated_vs_live_fair_post_strike_fix":{"n_orders":284,"windows":21,"mean_c":0.128,"mean_abs_c":0.328,"median_abs_c":0.209,"p90_abs_c":0.595,"share_abs_gt_1c":0.021,"bid_price_match_share":0.687},"validated_note":"Post-fix means after PR #23 (2026-10-13 06:34 UTC). Before the fix the bot used the Coinbase opening price as its strike, so its logged fair differs (mean |d| 8.3c); the dataset applies the current rule to every window.","sim_style_binance_fair_x1.45_vs_live_post_fix":{"mean_abs_c":1.653,"median_abs_c":1.282,"share_abs_gt_1c":0.609,"bid_price_match_share":0.204},"sigma_note":"Coinbase adjacent-second sigma runs about 1.5x the Binance kline sigma (0.53 vs 0.35 bp). That ratio is where the sim's 1.45 scale comes from; the replica needs no scale."},"fill_models":{"strict":"Up bid at P fills on a print with taker side no and yes_price < P; Down bid fills on a print with taker side yes and 1-yes_price < P (the price traded through the bid, so it fills regardless of queue)","touch":"Same with <= P (optimistic about queue position)","window":"(s, s+H] by print created_time; the first qualifying print is the fill time","validated_vs_live_rest_orders":{"all":{"orders":759,"live_filled":77,"strict":{"both":17,"live_only":60,"tape_only":2,"agree":0.918},"touch":{"both":68,"live_only":9,"tape_only":13,"agree":0.971}},"post_fix":{"orders":258,"live_filled":53,"strict":{"both":10,"live_only":43,"tape_only":1},"touch":{"both":45,"live_only":8,"tape_only":8}}},"reading":"For the bot's small clips, touch reproduces the live fills. Strict is the conservative lower bound."},"labels":{"y_dt_{strict,touch}":"seconds from s to the first qualifying print in (s, s+5]; NaN = no fill. A pull takes effect about 0.3 s after s, so fills with y_dt < 0.3 cannot be avoided.","y_fill_{mode}_{1,2,5}":"filled in (s, s+H]","y_vol_{mode}_{1,2,5}":"qualifying contracts in (s, s+H]","y_mo{5,10,30,60}_{mode}":"side markout per contract at the first fill: mark(t_fill+h) - P, where mark = median YES print in [T-1, T+1], widened to ±3 s then ±5 s; 0 fills had a missing mark","y_mofair{30,60}_{mode}":"same, marked with the replica fair","y_settle_{mode}":"side payout - P, for filled units","y_toxic_{mode}":"filled within 5 s AND mo30 < 0 AND mo60 < 0","y_cls_{mode}_{1,2,5}":"0 = not filled, 1 = filled and fine, 2 = filled and toxic","y_side_won":"settlement result; a label only, never a feature"},"features":{"count":121,"information_rule":"A feature at s uses Kalshi prints with t < s - lag_k, Coinbase trades with t < s - lag_c and Binance aggTrades with t < s - lag_b; a 1 s bar u is used only when u + 1 <= cutoff. main: all lags 0. lagged: kalshi 0.25 s, coinbase 0.45 s (the median Coinbase tick age at live decisions), binance 0.30 s (assumed).","side_convention":"Returns, drifts, imbalances, z and distances are signed so that positive = good for the bid's side","families":{"time_level":["f_left","f_elapsed","f_hour_utc","f_fair","f_fair_up","f_price","f_edge"],"fair_dynamics":["f_dfair_1","f_dfair_3","f_dfair_5","f_dfair_10","f_fair_bn","f_fair_bn_gap","f_fair_lead","f_fair_lead_gap"],"strike_vol":["f_z","f_dist_bp","f_dist_usd","f_dist_sig1","f_delta_per_bp","f_sigma_cb_bp","f_sigma_cb_n","f_sigma_bn_bp","f_rv_bn60_bp","f_rv_bn300_bp","f_rv_cb60_bp","f_sig_ratio_60_3600"],"binance_ticks":"f_bn_ret_{0.5,1,3,5,10,30,60}, f_bn_{n,vol,imb}_{0.5,1,3,5}, f_bn_maxq_1, f_bn_age, f_bn_range_{1,5}","coinbase_ticks":"f_cb_ret_{0.5,1,3,5,10,30,60}, f_cb_{n,vol,imb}_{0.5,1,3,5}, f_cb_maxq_1, f_cb_age, f_cb_range_{1,5}","cross_venue":["f_bncb_dev","f_bn_minus_cb_ret_1","f_bn_minus_cb_ret_3"],"kalshi_prints":"f_k_{nhit,vhit,nlift,vlift}_{0.1,0.5,1,3,5}, f_k_hit_share_5, f_k_n60, f_k_v60, f_k_burst_1_60, f_k_last, f_k_last_gap, f_k_drift_{1,3,5,10,30}, f_k_vwap5_gap, f_k_ask, f_k_bid, f_k_spread, f_k_mid_gap, f_k_ask_minus_price, f_k_price_minus_bid, f_k_age, f_k_age_hit, f_k_vhitle_{1,5}, f_k_age_hitle, f_k_maxhit_5, f_k_minhit5_minus_price"},"definitions":"hit = a taker selling into this side's bids; lift = a taker buying this side. f_fair_bn is the sim-style Binance fair (basis-adjusted, sigma x 1.45). f_fair_lead is the Binance price moved onto the Coinbase scale (300 s mean gap) and run through the bot's formula. There is no historical Kalshi order book, so ask, bid and spread are print proxies.","advice":"Leave f_hour_utc and window_idx out of models: with 1.5 days of data they identify the time of day. f_k_age_hitle is NaN 31 % of the time (no hit at or below the bid in the last 60 s)."},"no_lookahead_audit":{"method":"Rebuild sampled units from inputs truncated at each unit's cutoff and compare every f_ column; as a power check, the same truncation must flip y_fill_touch_5 on units that filled","main":{"n":300,"mismatch_units":0,"power_check":"30/30 flipped"},"lagged":{"n":150,"mismatch_units":0,"power_check":"30/30 flipped"}},"label_stats_main_primary_set":{"format":"[window-clustered mean in cents per contract at the first fill, t]","TRAIN":{"strict_H1":{"fill_rate":0.03396,"fills":2503,"toxic_share":0.4491,"mo30":[-2.01,-6.31],"mo60":[-2.2,-5.33]},"strict_H2":{"fill_rate":0.06389,"fills":4709,"toxic_share":0.4513,"mo60":[-2.15,-5.6]},"strict_H5":{"fill_rate":0.13686,"fills":10088,"toxic_share":0.4564,"mo60":[-2.31,-6.43]},"touch_H1":{"fill_rate":0.09974,"fills":7352,"toxic_share":0.4048,"mo30":[-0.62,-1.99],"mo60":[-0.98,-2.05]},"touch_H2":{"fill_rate":0.13471,"fills":9929,"toxic_share":0.402,"mo60":[-0.99,-2.28]},"touch_H5":{"fill_rate":0.21168,"fills":15603,"toxic_share":0.4023,"mo60":[-1.1,-3.12]}},"VAL":{"strict_H1":{"fill_rate":0.04137,"fills":1050,"toxic_share":0.4543,"mo60":[-1.11,-1.51]},"strict_H2":{"fill_rate":0.07494,"fills":1902,"toxic_share":0.4458,"mo60":[-0.91,-1.46]},"strict_H5":{"fill_rate":0.1524,"fills":3868,"toxic_share":0.4418,"mo60":[-0.95,-1.98]},"touch_H1":{"fill_rate":0.1225,"fills":3109,"toxic_share":0.3956,"mo60":[-0.08,-0.11]},"touch_H2":{"fill_rate":0.16084,"fills":4082,"toxic_share":0.3905,"mo60":[0.01,0.01]},"touch_H5":{"fill_rate":0.24236,"fills":6151,"toxic_share":0.3851,"mo60":[-0.15,-0.33]}},"lagged":"in lagged_build.json; close to main (TRAIN strict mo60 -2.17c, t -5.09)"},"sources":{"kalshi_tapes":"120 on-hand windows, all usable (KXBTC15M-26OCT120300-00 .. 131245-45), taken from 6 scratchpad dirs; 9 tickers had duplicate copies holding the same prints in a different order","binance_aggtrades":"1,321,697 rows: data.binance.vision daily 2026-10-12 (sha256 matches the .CHECKSUM) plus data-api.binance.vision REST for 2026-10-13 00:00-09:02 and 11:40-16:47 UTC; one id gap, on purpose. Check against the existing 1 s klines: 137,317 s compared, 99.9993 % exact match.","coinbase_trades":"577,089 rows from api.exchange.coinbase.com BTC-USD trades, 2026-10-12 05:40 to 2026-10-13 09:02 and 11:40-16:47 UTC; trade_id contiguous","coverage":"no exchange-id gaps in any of the 116 window spans; longest silence 6.8 s on Binance, 13.4 s on Coinbase"},"variants_counted":{"label_variants":"2 fill models x 3 horizons = 6 class labels, plus stored markout and settle columns; no label was chosen by looking at VAL or TEST","dataset_variants":["main (lags 0)","lagged (0.25 / 0.45 / 0.30 s)"],"builds_run":5,"builds_detail":"2 smoke builds, 1 full build thrown away because its split had 4 unquotable windows inside TRAIN (it produced TRAIN/VAL stats only), then main and lagged on the frozen split","models_fit":0,"train_only_look":"one univariate quintile table on main TRAIN"},"caveats":["Only 1.5 days of data (116 windows): small for ML. Cluster every test by window.","Every second x both sides means neighbouring units share fills, so the effective sample size is far below the row count.","There is no Kalshi book history: queue position is unknown and strict/touch only bound it.","The tapes include the live bot's own fills from 2026-10-12 23:00 UTC onward.","The counterfactual bid ignores the bot's 1c reprice band, its inventory guards and the one-sided starter."]}


---
## result 1 

**Bid-puller ML: result**

**Verdict: nothing here is profitable, so there is nothing to launch.** The model predicts very well that a resting bid is about to be hit (AUC about 0.85 to 0.88). It cannot tell a toxic fill from a fine one. Pulling on it loses money on VAL in every strict cell. TEST was never opened.

All work is under `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_toxicity/model` (177 MB, including the venv). Paths below are relative to that.

**Setup**
- **Data.** The lagged information set (Kalshi 0.25 s, Coinbase 0.45 s, Binance 0.30 s).
  - Every unit was rebuilt with the bid moved -3 to +3 c. I used a copy of the data lane's `features.py` with one line changed, and labels were recomputed at the moved price. The offset-0 rows match `lagged_{train,val}.parquet` exactly (0 mismatched columns).
  - The move was needed because a live bid can sit away from fair minus 3c (it only reprices after a 1c fair move), and the replay's bid comes from a different fair.
  - Training rows: crosses_ask_proxy False; offset 0 plus 2 random moved offsets per unit (215k rows).
- **Target.** y_cls_strict_2 == 2: a strict fill within 2 s that marks out below the bid at 30 s and 60 s. Fixed before any fit.
- **Features.** 119: all 121 f_ columns except f_hour_utc and f_elapsed.
- **Walk-forward on TRAIN.** First fit on windows 0..19, then folds 20-29 through 60-69. Each fold is predicted by a model fit on all earlier windows, and settings were chosen by the out-of-fold (OOF) log loss.
  - Chosen GBM: LightGBM with 7 leaves, min_data 1000, learning rate 0.06, 75 rounds.
  - Chosen logistic regression: C = 0.002.
  - Calibration: Platt on VAL offset-0 rows. It is monotone, so it cannot change any pull decision.
- **Replays.**
  - bn145 (as specified): your `sim.py` with sigma x1.45, on rebuilt arrays. On the 86 windows it shares with `w90_s1.45`, P&L is identical.
  - replica (robustness): the same replay with the bot's own Coinbase fair.
  - My copy of the simulator reproduces `sim.simulate` exactly when no pull is set.
  - Bot = live rule at ladder rung 0 (5-contract clip, $10 per window). Placing stays at 0.3 s; the tested cancel latency applies to every cancel, including the baseline's reprice cancels.

**1. Model metrics** (offset 0, quotable rows; AUC 90% interval is a window bootstrap)

| | AUC | AP lift | log loss (base) |
|---|---|---|---|
| GBM, TRAIN OOF | 0.849 [0.830, 0.867] | 4.85 | 0.1230 (0.1538) |
| LR, TRAIN OOF | 0.844 [0.825, 0.864] | 4.93 | 0.1243 (0.1538) |
| GBM, VAL | 0.877 [0.856, 0.895] | 5.87 | 0.1188 (0.1564); 0.1178 calibrated |
| LR, VAL | 0.871 | 5.91 | 0.1202 (0.1564) |

- GBM AUC by fold: 0.797, 0.842, 0.840, 0.879, 0.877.
- Other labels (OOF GBM AUC): strict 1 s 0.876, strict 5 s 0.805, touch 1 s 0.901, touch 2 s 0.870, touch 5 s 0.814.
- Single features (OOF AUC): f_k_price_minus_bid alone 0.826; -f_dfair_1 0.577; |f_dfair_5| 0.552; -f_bn_ret_1 0.554; f_k_vhit_1 0.514.

**2. Adverse-selection skill given a fill (the key finding)**
- **Joint model, toxic vs fine among strict-filled units:** AUC 0.521 on TRAIN OOF, 0.564 on VAL.
- **Dedicated model trained only on filled units:** OOF AUC 0.500 / 0.489 / 0.492 (three round settings). Rank correlation with the 60 s markout is -0.03.
  - On TRAIN, the fills it calls most toxic (top fifth) mark out better than the rest: -0.69c vs -1.55c per fill.
  - On VAL (one look): AUC 0.571; top fifth -0.13c vs rest -0.80c, the wrong way again.
- **By score decile (VAL):** fill rate rises from 0.1% to 40%, but the toxic share of fills stays at 0.22 to 0.52 with no trend. The top decile's 60 s markout is -0.98c per fill (t -1.1).

**3. Feature importances** (GBM gain share / VAL AUC drop when the feature is shuffled)

| feature | gain | VAL AUC drop |
|---|---|---|
| f_k_price_minus_bid | 0.603 | 0.165 |
| f_k_ask_minus_price | 0.088 | 0.007 |
| f_k_minhit5_minus_price | 0.044 | 0.003 |
| f_k_age_hitle | 0.040 | 0.005 |
| f_fair_bn | 0.034 | 0.006 |
| f_left | 0.026 | 0.006 |
| f_delta_per_bp | 0.025 | 0.002 |
| f_sigma_bn_bp | 0.013 | 0.001 |
| f_dist_sig1 | 0.009 | |
| f_k_ask | 0.007 | 0.002 |

- Binance and Coinbase tick features are each at most 0.005 of the gain; f_k_nhit_0.1 is 0.006.
- Largest logistic-regression terms: f_k_ask_minus_price -0.42, f_k_price_minus_bid +0.40, f_delta_per_bp +0.38.

**4. Thresholds** (chosen on TRAIN OOF windows 20..69, bn145, strict fills, 0.25 s cancel latency; 14 values for each of 3 rules)
- **c (GBM, per side):** threshold 0.02 (+8.7c vs no pull, t 0.36). Every other threshold up to 0.3 lost 4 to 30c, so the curve is noise.
- **c_lr (logistic regression, per side):** 0.12.
- **c_both (GBM, pull both sides):** 0.03, which pulls 61% of the time.
- Calibrated equivalents: c 0.0129, c_both 0.0214, c_lr 0.132.

**5. Replay, strict fills** (cents per window, with window-clustered t). The ML thresholds were chosen on these same TRAIN windows. "vs a" is the paired difference from no pull.

Rules:
- **a:** no pull.
- **b:** your simple rule, both sides pulled for 5 s after a 1c fair move within 5 s.
- **b2:** the simple rule, but only the side the move goes against.
- **c, c_lr, c_both:** the ML rules above.
- **r:** random pulls at the same pull share as c (placebo).

bn145 replay:

| | 0.1 s | 0.25 s | 0.5 s | 1.0 s |
|---|---|---|---|---|
| a, TRAIN | -15.0 (-0.9) | -33.5 (-2.1) | -26.5 (-1.6) | -19.3 (-1.2) |
| a, VAL | -45.5 (-1.7) | -49.6 (-1.8) | -50.8 (-1.8) | -39.3 (-1.6) |
| b vs a, TRAIN | +36.3 (1.7) | +43.0 (1.9) | +39.3 (1.8) | +33.1 (1.4) |
| b vs a, VAL | +12.1 (0.5) | +2.2 (0.1) | +9.8 (0.3) | +3.9 (0.1) |
| b2 vs a, TRAIN | +23.6 (1.2) | +25.1 (1.3) | +32.9 (1.6) | +30.4 (1.5) |
| b2 vs a, VAL | -26.3 (-1.4) | -24.4 (-1.3) | -23.4 (-1.2) | -20.4 (-1.1) |
| c vs a, TRAIN | -10.8 (-0.4) | +8.7 (0.4) | +9.2 (0.4) | -10.7 (-0.5) |
| **c vs a, VAL** | **-20.8 (-0.5)** | **-28.6 (-0.7)** | **-22.4 (-0.6)** | **-57.6 (-1.7)** |
| c_lr vs a, TRAIN | -11.8 | +0.6 | -3.4 | +11.2 |
| c_lr vs a, VAL | -2.8 | +11.9 (0.5) | -0.9 | -4.8 |
| c_both vs a, TRAIN | +15.4 | +36.8 (1.7) | +36.8 (1.8) | +12.1 |
| c_both vs a, VAL | +56.6 (1.7) | +55.1 (1.7) | +55.4 (1.7) | +44.3 (1.4) |
| r vs a, TRAIN | | +13.8 (0.7) | | |
| r vs a, VAL | | +11.6 (0.8) | | |

c vs the simple rule b on VAL at 0.25 s: -30.8 (t -0.7).

Replica replay, VAL, vs a:

| | 0.1 s | 0.25 s | 0.5 s | 1.0 s |
|---|---|---|---|---|
| a (no pull, level) | -9.9 | -18.7 | -16.6 | -11.8 |
| b | -11.4 | -9.0 | -10.6 | -31.3 |
| **c** | **-70.4 (-1.7)** | **-65.5 (-1.7)** | **-71.9 (-1.7)** | **-74.9 (-2.0)** |
| c_lr | +9.2 | +7.0 | -4.8 | -2.1 |
| c_both | +23.3 | +25.4 | +16.3 | +11.1 |

Placebo r: +22.4. On replica TRAIN, c is -0.1, +3.6, +5.6, -23.2 vs a across the four latencies.

Detail at 0.25 s, bn145 replay, strict fills (markouts are per maker-fill contract):

| | c/window (t) | worst window | maker fills (contracts) | locks | pairs/window | mark-out 10 s | mark-out 60 s (t) | pull share |
|---|---|---|---|---|---|---|---|---|
| TRAIN a | -33.5 (-2.1) | -269 | 231 (820) | 35 | 9.0 | -1.45 | -1.36 (-1.3) | 0 |
| TRAIN b | +9.5 (0.5) | -287 | 163 (623) | 38 | 7.5 | -1.68 | -1.08 (-0.9) | 0.36 |
| TRAIN c | -24.8 (-1.3) | -287 | 75 (290) | 34 | 4.2 | -1.82 | -1.57 (-1.1) | 0.33 |
| TRAIN c_both | +3.3 (0.2) | -292 | 51 (219) | 22 | 2.9 | | -3.34 | 0.61 |
| VAL a | -49.6 (-1.8) | -220 | 96 (350) | 16 | 8.7 | -1.02 | -3.73 (-3.2) | 0 |
| VAL b | -47.3 (-1.4) | -215 | 61 (248) | 20 | 6.9 | | -4.54 | 0.28 |
| VAL c | -78.1 (-2.9) | -256 | 31 (136) | 13 | 4.0 | | -5.55 (-2.6) | 0.20 |
| VAL c_lr | -37.7 (-1.2) | -235 | 85 (309) | 17 | 7.7 | | -5.76 | 0.06 |
| VAL c_both | +5.6 (0.2) | -220 | 20 (83) | 10 | 2.5 | | -3.62 | 0.65 |
| VAL r | -38.0 (-1.7) | -235 | 79 (307) | 18 | 7.6 | | -3.65 | 0.23 |

Replica, VAL, 0.25 s: a -18.7, worst -215, 112 fills; c -84.2 (t -3.0), worst -270, 26 fills, 60 s markout -8.19c, 3.3 pairs per window. On VAL, c was better in 8 windows and worse in 13 (bn145), and better in 6, worse in 16 (replica).

**6. Touch fills, 0.25 s, vs a**
- bn145 TRAIN: b +19.0, b2 +24.4, c -18.5, c_lr +10.2, c_both +0.4, r +7.7.
- bn145 VAL: b -2.5, b2 -50.5 (t -1.8), c -52.6 (t -1.4), c_lr -16.1, c_both +5.9, r -19.2.
- Replica VAL: b +28.2 (t 1.3), b2 +38.2, c -66.0 (t -2.2), c_both +24.2, r +29.3.

**7. Old $10-caps rule (10 contracts), bn145, strict, 0.25 s, vs a**
- TRAIN: c -52.4 (t -1.3), b +13.2.
- VAL: c -86.6 (t -1.1), b -45.1, c_both +76.6 (t 1.5), r +17.2.

**What this means**
- **Why c loses.** The score mostly says "my bid is at or above the last print bid" (f_k_price_minus_bid). Pulling on it removes the fills that were coming, toxic or not, including completion fills. Pairs per window fall from about 9 to about 4, the inventory left unpaired goes to the taker lock, and the fills that remain mark out worse.
- **Why c_both and the placebo look positive.** The baseline loses in the strict replay, so quoting less loses less. Random pulls give similar gains.
- **Simple rule b.** Positive on TRAIN (t 1.9) but about zero on bn145 VAL and -9 on replica VAL. Not proven.
- **The bn145 replay doesn't fit the model well.** In it, 31% of the bot's bids sit more than 3c from the live-fair bid, so the lookup is clipped at the edge. In the replica replay only 1% are. The replica result for c is worse anyway.
- **Not enough evidence.** With a per-window standard deviation of $1.5 to $2.5 and about 292 policy evaluations, nothing here would survive correcting for the number of variants.
- **What might be missing.** Decisions run once a second. With no historical order book, queue position is unknown, and Kalshi flow features carry almost no weight. Informed flow that arrives 0.8 to 1.8 s before spot moves is not visible to these features.

**Frozen model** (for the record; rule c already fails VAL)
- GBM: `frozen/gbm_strict2.txt`
- Logistic regression: `frozen/lr_strict2.pkl` and `frozen/lr_strict2.json`
- Features: `frozen/features.json` (119 = the manifest's 121 f_ columns minus f_hour_utc and f_elapsed)
- Calibration: `frozen/platt_val.json` (GBM a = 0.482, b = 1.239)
- Thresholds and spec: `frozen/frozen_spec.json`. Raw: c 0.02, c_both 0.03, c_lr 0.12.
- Rule c: pull a side while the GBM score of its bid, at the bid's own price, is above 0.02; re-allow when it drops.

**Files**
- Tables: `out/policy_table.csv`, `out/policy_per_window.csv`, `out/tau_selection.json`
- Model results: `out/train_report.json`, `out/diag.json`, `out/conditional_toxicity.json`
- Logs: `out/train.log`, `out/evaluate.log`
- Data: `dataset/off_{train,val}.parquet`, `sim_data/{bn145,replica}.npz`
- Code: `code/` (build_sim, build_off, features_off, train, models, sim_pull, policies, evaluate, diag, cond)

**TEST runner.** `code/run_test_once.py` is written and compiles but was not run. It refuses to run a second time. I would not spend TEST on rule c, since it already fails VAL; whether to spend it on b or not at all is your call.

**Variants counted**
- 1 offset-augmented dataset (7 offsets); 2 replay builds.
- 2 training runs: the first was stopped for speed before any fold result printed; the second completed.
- GBM: 2 settings x 20 round checkpoints. Logistic regression: 3 C values.
- 5 extra labels (record only); 7 single-feature AUCs; conditional models: 3 round settings x (classifier + Huber regressor).
- 42 threshold-selection replays.
- About 250 table replays: 7 rules x 4 latencies x 2 fill models x 2 replays x 2 splits, plus the $10-caps runs.

No orders, keys, Railway changes, deploys or pushes; nothing written under /home/user/Claude; TEST not opened.


---
## result 2 

**Skeptic review of the bid-puller ML lane: the "nothing to launch" verdict holds, and holds more firmly than the lane said.**

I re-ran `train.py`, `evaluate.py`, `diag.py` and `cond.py` into my own folder. Every output is bit-identical to the lane's: frozen models, predictions, `train_report` (all but run time), `policy_table`, `policy_per_window`, `tau_selection`, `diag` and `conditional_toxicity`. So the reported numbers are right. My corrections come from extra checks: placebos matched to each rule's own pull pattern, a "never quote" baseline, bootstrap intervals, and an independent leakage audit. All results below are strict fills at 0.25 s cancel latency unless noted.

**Verdict per claim**

1. **No look-ahead in features or labels: confirmed.**
   - I rebuilt 400 sampled rows of the lane's own offset dataset (200 TRAIN, 200 VAL, all 7 price offsets, half of them filled) with every input cut exactly at its cutoff. 0 rows mismatched on any of the 121 feature columns.
   - Power check: cutting the Kalshi tape 0.1 s earlier than allowed changed 339 of the 400 rows, so the test can see a leak.
   - My own recompute from the raw tapes of 8 Kalshi features, `crosses_ask_proxy` and the strict fill time matched on all 400 rows.
   - The offset-0 rows equal the data lane's lagged files in every column (95,026 TRAIN rows, 31,976 VAL rows).

2. **Split used correctly: confirmed.** The split runs in time order (TRAIN, then VAL, then TEST). Each walk-forward fold is fit only on earlier windows. No code reads TEST and no `model/test` folder exists. File access times can't prove TEST was never opened, because this filesystem only updates them once a day.

3. **No threshold tuned on VAL: confirmed.**
   - Rounds, C and every threshold were chosen on TRAIN out-of-fold windows. The VAL calibration is monotone, so it can't change a pull decision. Its VAL log loss of 0.1178 is measured on the same data it was fit on, so it reads a little optimistic.
   - New point: rule c's threshold of 0.02 is the lowest value in the grid and sits below the 3.6% base rate. It pulls the top 40% of units, which means it turns away most fills. It was the only positive grid value on TRAIN (+8.7c, t 0.36), so it was picked out of noise.

4. **AUC 0.85 to 0.88: confirmed, but this is fill prediction, not toxicity.**
   - One feature, `f_k_price_minus_bid` (is my bid at or above the last price takers sold at), gets 0.826 out-of-fold and 0.858 on VAL by itself.
   - 25% of the toxic positives fill within 0.25 s, before a cancel can land. With those removed, AUC is 0.828 out-of-fold and 0.858 on VAL.

5. **"Can't tell a toxic fill from a fine one": slightly weakened, but the conclusion stands.**

   | Toxic vs fine, among strict-filled units | AUC | 90% window bootstrap | draws at or below 0.5 |
   |---|---|---|---|
   | Joint model, VAL | 0.564 | [0.524, 0.600] | 0.3% |
   | Dedicated model, VAL | 0.571 | [0.515, 0.631] | 1% |
   | Joint model, TRAIN out-of-fold | 0.521 | [0.496, 0.548] | 8% |

   So on VAL the yes/no toxic label ranks slightly better than chance. It is worth nothing in money: the 60 s markout of the fifth of fills the model calls most toxic, minus the rest, is +0.67c on VAL [-1.2, +2.6]. That is zero, or the wrong sign.

6. **Rule c loses on VAL: confirmed, and it is worse than random.**
   - Placebo: each window gets rule c's pull flags from another window of the same split, which keeps the share and timing but breaks the link to the market.
   - On VAL, 92% of these placebos beat c in the Binance-fair replay and 100% in the replica-fair replay. With touch fills it is 98% and 100%.
   - Against never quoting at all, c loses 78.1c per window (t -2.87) in the Binance replay and 84.2c (t -2.95) in the replica. It throws away the bot's best fills, the completion fills.

7. **c_both's gain is just quoting less: confirmed, with a corrected placebo.**
   - On VAL (Binance replay) c_both is +55.1c vs no pull, but only +5.6c vs never quoting (t 0.21).
   - The lane's random placebo pulled about 23% of the time, against c_both's 65%. With a matched placebo, the mean is +45.3c [18.3, 76.5] and 26% of draws beat c_both. In the replica replay, 70% of draws beat it.

8. **Simple rule b "not proven": confirmed.**
   - TRAIN, Binance replay: +43.0c (t 1.91), and it beats the matched placebo (p 0.02; touch p 0.04). That is a real signal on TRAIN, beyond just quoting less.
   - It does not hold on VAL: +2.2c against a placebo mean of +12.8c (p 0.68). In the replica replay it is -9.0c against +23.9c (p 0.98).
   - b's own result on VAL is a loss: -47.3c per window (Binance replay) and -27.7c (replica).

9. **Gain of the ML over the simple rule: refuted; there is none.**
   - c minus b on VAL: -30.8c (t -0.71) Binance replay, -56.5c (t -2.06) replica, -94.2c (t -2.96) replica with touch fills.
   - c_both minus b is +52.9c (t 1.42), but that is the quote-less effect from claim 7.

10. **Replay too generous with cancels: not in a way that changes the verdict.**
    - The lane's simulator copy equals `sim.py` exactly with no pull (93 windows, both fill models, clip 5 and 10). The Binance replay equals the earlier `w90_s1.45` arrays on all 86 shared windows.
    - Fills between the decision and the cancel landing are kept. Moving the cancel or placing latency by 0.01 s shifts the no-pull baseline by at most 1.9c per window. Orders run 11 to 81 per window, so rate limits are not an issue.
    - Two real generosities: touch fills let a re-placed bid fill straight away with no lost queue place, which favours every pull rule; and the Binance replay's fair has no information lag while the ML features lag 0.25 to 0.45 s, which favours b there. Neither saves c: it fails at all 4 latencies, and also in the replica replay, where b has no information edge.

11. **Selection across variants: confirmed.**
    - 250 table cells plus 42 threshold runs make 292 evaluations.
    - Largest paired |t| over all cells is 2.56 (a TRAIN cell); VAL cells range from -2.47 to +1.83. Correcting for that many tests needs about |t| > 4, so nothing survives.
    - Minor correction: the paired per-window spread of (rule minus no pull) is $0.5 to $1.9, not the $1.5 to $2.5 the lane reported.

12. **Importances, per-fold AUCs and other-label AUCs: confirmed (identical on rerun).**

**What this means for launching.** In the VAL replay no rule beats simply not quoting. The best is c_both at +5.6c per window over never quoting (t 0.2). The current bot with no pull is itself at -49.6c (t -1.8) on strict fills and -22.8c (t -0.7) on touch fills on VAL (Binance replay). Do not spend TEST on c or c_both. b's prior is weak after it failed VAL; if TEST is used on it, pre-register b against the matched placebo and against never quoting.

Research only: no orders, keys, Railway changes, deploys or pushes. Nothing was written under /home/user/Claude, and TEST was not opened. The skeptic folder is 9.8 MB; it links to the model lane's dataset and simulator arrays instead of copying them.

Files are in /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_toxicity/skeptic:
- code/audit_leak.py
- code/repro_sim.py
- code/null_replay.py
- code/model_checks.py
- code/cond_ci.py
- code/extra_checks.py
- code/show_table.py
- out/audit_leak.json
- out/null_replay.json
- out/model_checks.json
- out/cond_ci.json
- out/rerun_train.log, out/rerun_evaluate.log, out/rerun_diag.log, out/rerun_cond.log
- rerun/out/, rerun/preds/, rerun/frozen/ (the full rerun, identical to the model lane's)


---
## result 3 

# Bid-puller ML: verdict

*Written Tue Oct 13, 3:14 PM PT. Research only: no orders, keys, Railway changes, deploys or pushes, and nothing written under /home/user/Claude.*

## The short answer

**No. Machine learning does not improve the pull guard. Nothing in this study makes money, so there is nothing to launch or scale.**

TEST was not used. The rule for opening it was that an ML pull rule beat both no-pull and the simple rule on the check windows with t of 2 or more, in the strict replay. No cell met that. TEST stays sealed for a future rule.

## What was tested

- **Data.** 116 Bitcoin 15-minute windows, Sun Oct 11 11:45 PM to Tue Oct 13 9:45 AM PT, split by time:
  - learn: the oldest 70 windows (through Mon 6:15 PM)
  - check: the next 23 (Mon 6:15 PM to midnight)
  - TEST: the newest 23 (Tue midnight to 9:45 AM), untouched
- **Model.** Every second, for each side, it asks one question: is my resting bid about to be filled by someone who knows the price is moving through it?
  - It uses 119 inputs the live bot has in time: Coinbase and Binance ticks, Kalshi prints, time left, distance to strike, and our fair.
  - The bot's real delays are built in.
  - An independent skeptic re-ran everything and got identical results. It found no look-ahead.
- **Replay.** The current bot (rung 0, 5-contract clip, $10 a window) was replayed with and without pulls, at 4 cancel speeds and with two fair models.
  - Two fill models: *strict* means the price traded through our bid; *touch* means it traded at our bid. Touch matches live fills better.

## Why ML doesn't help

1. **It predicts fills, not bad fills.**
   - It is very good at "my bid is about to be hit" (AUC 0.88), but one input does most of the work: whether our bid is at or above the price takers last sold at.
   - At telling a bad fill from a fine one, it is close to a coin flip (AUC 0.52 to 0.57). The fills it calls worst mark out no worse than the rest (+0.7c, range -1.2 to +2.6).
2. **Pulling on it throws away good fills too,** including the fills that complete our pairs.
   - Pairs per window fall from about 9 to about 4.
   - The leftovers go to the costly lock buy, and the fills that remain mark out worse.
3. **Random pulls beat it.** On the check windows, 92% to 100% of random pull schedules with the same amount and timing of pulling did better.
4. **The worst fills are too fast or invisible.**
   - A quarter of the bad fills land within 0.25 s, before any cancel can arrive.
   - The takers who hit us 0.8 to 1.8 s before spot moves leave no trace in the public feeds the model reads.

## Cents per window on the check windows, vs not pulling

- **Today's speed:** about 0.7 s from a Coinbase move to a cancel landing. That is a speed-plan estimate, since live cancels aren't timed yet. It sits between the 0.5 s and 1.0 s rows.
- **Target speed** after the speed work: about 0.12 s, the 0.1 s row.
- Each cell shows cents per window vs not pulling, with t in brackets. "Binance fair" and "bot fair" are the two replays.

**ML rule** (pull a side while the model's score for that bid is above 0.02):

| Cancel speed | Strict, Binance fair | Strict, bot fair | Touch, Binance fair | Touch, bot fair |
|---|---|---|---|---|
| 0.1 s (target) | -20.8 (-0.5) | -70.4 (-1.7) | -59.1 (-1.6) | -60.7 (-1.7) |
| 0.5 s | -22.4 (-0.6) | -71.9 (-1.7) | -34.3 (-1.0) | -64.5 (-2.2) |
| 1.0 s | -57.6 (-1.7) | -74.9 (-2.0) | -60.4 (-1.7) | -69.9 (-2.5) |

It loses 21 to 75 cents a window at every speed, target speed included.

**Simple rule** (the one already built: pull both sides for 5 s after a 1c fair move within 5 s):

| Cancel speed | Strict, Binance fair | Strict, bot fair | Touch, Binance fair | Touch, bot fair |
|---|---|---|---|---|
| 0.1 s (target) | +12.1 (0.5) | -11.4 (-0.4) | -11.2 (-0.3) | +22.4 (1.0) |
| 0.5 s | +9.8 (0.3) | -10.6 (-0.3) | +41.8 (1.1) | +43.9 (1.8) |
| 1.0 s | +3.9 (0.1) | -31.3 (-1.2) | +4.3 (0.1) | +25.3 (1.0) |

- It comes out about zero: -31 to +44 cents, never reaching t 2.
- On the check windows, random pulls at the same rate did as well.
- On the learning windows it did beat random pulls (+43c, p 0.02). That is why it is worth a live test, but not worth more size.

**A result to ignore.** An ML variant that pulls both sides 65% of the time shows +55c vs not pulling (t 1.7). That gain comes only from quoting less:
- It is only +5.6c (t 0.2) better than never quoting at all.
- Random pulls at the same rate get +45c.

**The bigger picture.**
- With no pull, the current bot lost 49.6c a window on strict fills (t -1.8) and 22.8c on touch fills (t -0.7) over the check windows. In this replay, no rule beats simply not quoting.
- About 290 rule-and-setting combinations were scored. The best |t| anywhere was 2.6, and that many tries needs about 4 before anything counts.

## What to plug into the live pull guard

- **No model and no threshold.** Do not load `model/frozen/gbm_strict2.txt` or any ML rule.
- **Keep the simple guard as built.** It is on branch `claude/kalshi-pull` (703d942) and was not merged or live as of 3:14 PM PT. The settings:
  - `SPEEDDESK_KALSHI_PULL=true`
  - `SPEEDDESK_KALSHI_PULL_MOVE=0.01`
  - `SPEEDDESK_KALSHI_PULL_LOOKBACK_S=5`
  - `SPEEDDESK_KALSHI_PULL_HOLD_S=5`

  This is the replayed rule. Live, it also triggers on a 1c round trip inside 5 s, so it pulls slightly more often. Lock buys stay exempt.
- **Don't retune those numbers on this data;** that would be fitting noise.
- **Don't switch to pulling only the side the move goes against.** That version lost 20 to 26c a window in the strict Binance-fair replay. It was mixed in the other replay.
- **Judge it live against the practice twin,** which never pulls. Expect about zero.
  - If the live spread is like the replay's ($0.5 to $1.9 a window), a real +10c a window gain needs roughly 100 to 1,400 windows to show at t 2. That is 1 to 15 days of round-the-clock trading.
  - Turn it off if real trails the twin at t -2 or worse. Call it a win only at t +2 or better.
  - The twin's fills are practice fills, so a small gap means little.
- **Size:** nothing here earns more size; let the ladder decide on real P&L.
- **Stops:** nothing here supports dropping the daily or lifetime stops. The no-pull bot loses money in this replay.

## What data would make it better

1. **The new recorder's books.**
   - The recorder is on `claude/kalshi-recorder`. It is off by default and not deployed. It saves the current and next KXBTC15M order book every second.
   - That gives three things the trade tapes can't:
     - how much size is queued ahead of our bid (today we only know a fill lands somewhere between strict and touch)
     - the real best bid and ask, instead of guesses from prints
     - other makers pulling their size just before a move, the classic warning sign
   - It records KXBTC15M books only when it runs as its own Railway service; inside the bot it skips them.
   - Once its 2 GiB cap fills, it drops KXBTC15M books older than 72 h. Give it room for 2 to 3 weeks.
2. **Sub-second books.** One snapshot a second is slow for a race that lasts 0.1 to 1.8 s. The live bot already gets the WebSocket book with its key; log every change with its receive time.
3. **Our own order clock.** Log Kalshi's timestamp on every create and cancel reply, and every fill that landed after we had sent a cancel. That gives the real cancel speed and the real list of fills we were too slow to dodge.
4. **The twin's kept bids.** Each pulled bid's twin copy shows whether it would have filled and how it marked out. That is a ready-made label for the next model.
5. **More days.** 1.5 days and 116 windows is small for ML.
   - Refit after 2 to 3 weeks (about 1,500 to 2,000 windows), with the same rules: time split, one look at the check windows, one TEST.
   - Score the next model on money after the fill, not on predicting fills.

## Files

Paths are under `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_toxicity/`.

- **This verdict:** `VERDICT.md`
- **Data:** `data/manifest.json`. The TEST files are `data/out/dataset/*_test.parquet`, never opened.
- **Model lane:**
  - `model/out/policy_table.csv` and `model/out/policy_per_window.csv`
  - `model/out/train_report.json` and `model/out/conditional_toxicity.json`
  - `model/frozen/` (frozen record only; not for live use)
  - `model/code/run_test_once.py`, never run (no `model/test/USED` marker)
- **Skeptic:**
  - `skeptic/out/null_replay.json`: matched placebos and the never-quote baseline
  - `skeptic/out/cond_ci.json`
  - `skeptic/out/audit_leak.json`
