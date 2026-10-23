# Z4 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **History:** outcome records from splits ['train'] (3863 records of 3863 usable coins); structural pool 5435 graduates (4379 with a creator and a theme token, 3418 distinct tokens); first structural graduation 2026-10-01 00:01:23 UTC.
- **Written:** 2026-10-09 05:16:48 UTC; runtime 48.7 s; PREREG sha256 `a3f2b8a32e7e`; trials in the ledger: 2631.
- **Overall Z4 status:** NO EDGE (nothing qualified on TRAIN: neither momentum nor exhaustion).

## Event counts at the decision (first grid time ≥ g + 30 min; no returns)

- Coins: 3863; alive at the decision: 1408.

| N | status (all coins) | coins with ≥ 1 member | HOST entries (eligible, alive) | per day | MOM θ=0.25 | MOM θ=1 | crowded (k ≥ 3) | exact clone | instant | warm-up | keys |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3h | {'solo': 1963, 'eligible': 1472, 'unknown': 323, 'pending': 105} | 1577 | 508 | 127.0 | 65 | 25 | 191 | 309 | 414 | 9 | 159 |
| 12h | {'eligible': 2064, 'solo': 1384, 'unknown': 323, 'pending': 92} | 2156 | 697 | 174.2 | 102 | 34 | 469 | 502 | 556 | 70 | 212 |

- Top primary keys of HOST entries, N = 3h: {'fund': 64, 'super': 31, 'cat': 24, 'elon': 16, 'american': 15, 'google': 15, 'gta': 13, 'oil': 12, 'beast': 12, 'space': 12, 'agency': 10, 'vsof': 8}.
- Top primary keys of HOST entries, N = 12h: {'fund': 71, 'super': 33, 'cat': 26, 'oil': 18, 'american': 18, 'google': 18, 'elon': 16, 'space': 15, 'gta': 14, 'agency': 14, 'udr': 13, 'beast': 12}.

## Configs

| role | config | n | keys | mean | 90% CI coin | 90% CI 6-h block | 90% CI key | w/o top 2 | w/o best key | placebo diff (members) | placebo diff (unmatched) | diff vs market heat | costs ×1.5 | ρ(heat, ret) |
|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| mom|N3h|th0.25 | mom|N3h|th0.25 | 65 | 34 | -39.8% | [-52.0, -26.4] | [-54.9, -21.6] | [-64.6, -17.1] | -46.3% | -52.3% | -3.3% | -5.1% | -9.1% | -40.7% | -0.148 |
| mom|N3h|th1 | mom|N3h|th1 | 25 | 18 | -51.5% | [-67.7, -34.6] | [-70.3, -31.4] | [-71.0, -30.3] | -59.8% | -55.1% | -14.8% | -20.4% | -18.7% | -52.4% | 0.283 |
| mom|N12h|th0.25 | mom|N12h|th0.25 | 102 | 56 | -48.0% | [-59.3, -36.1] | [-61.3, -32.5] | [-62.9, -32.2] | -54.2% | -55.6% | -11.3% | -14.4% | -14.4% | -48.8% | -0.033 |
| mom|N12h|th1 | mom|N12h|th1 | 34 | 25 | -60.8% | [-74.6, -45.7] | [-76.9, -42.2] | [-74.4, -45.9] | -68.8% | -65.7% | -22.0% | -28.6% | -31.9% | -61.5% | 0.014 |
| host|N3h | host|N3h | 508 | 159 | -35.8% | [-42.2, -28.4] | [-44.9, -24.5] | [-46.2, -26.0] | -39.9% | -38.9% | +1.3% | -0.6% | n/a | -36.7% | 0.284 |
| host|N12h | host|N12h | 697 | 212 | -36.7% | [-42.0, -30.7] | [-44.9, -26.9] | [-45.9, -28.2] | -40.0% | -38.9% | +2.2% | -1.6% | n/a | -37.6% | 0.238 |

- mom|N3h|th0.25 diagnostics: by tag {'hot|crowd': {'n': 35, 'mean': -0.2507191332164363}, 'hot|few': {'n': 30, 'mean': -0.5703184704368109}}; by link {'exact_clone': {'n': 33, 'mean': -0.4700697852761352}, 'token_only': {'n': 32, 'mean': -0.324138151923973}}; by speed {'instant': {'n': 49, 'mean': -0.4026311034365068}, 'slow': {'n': 16, 'mean': -0.38473748170567246}}; warm-up {'full_lookback': {'n': 64, 'mean': -0.40629694360124446}, 'warmup': {'n': 1, 'mean': 0.11828061480004436}}.
- mom|N3h|th1 diagnostics: by tag {'hot|crowd': {'n': 11, 'mean': -0.44991475749263543}, 'hot|few': {'n': 14, 'mean': -0.5668735969212616}}; by link {'exact_clone': {'n': 11, 'mean': -0.5546559940052412}, 'token_only': {'n': 14, 'mean': -0.48457691108992834}}; by speed {'instant': {'n': 18, 'mean': -0.629732065490994}, 'slow': {'n': 7, 'mean': -0.22144507292553708}}; warm-up {'full_lookback': {'n': 24, 'mean': -0.5418155543381956}, 'warmup': {'n': 1, 'mean': 0.11828061480004436}}.
- mom|N12h|th0.25 diagnostics: by tag {'hot|crowd': {'n': 66, 'mean': -0.47439443730460423}, 'hot|few': {'n': 36, 'mean': -0.489995941735383}}; by link {'exact_clone': {'n': 75, 'mean': -0.535114911850373}, 'token_only': {'n': 27, 'mean': -0.32652845836295147}}; by speed {'instant': {'n': 82, 'mean': -0.49020347853747936}, 'slow': {'n': 20, 'mean': -0.43766007622521774}}; warm-up {'full_lookback': {'n': 93, 'mean': -0.49055486104494717}, 'warmup': {'n': 9, 'mean': -0.36980940971084125}}.
- mom|N12h|th1 diagnostics: by tag {'hot|crowd': {'n': 20, 'mean': -0.6636757788524783}, 'hot|few': {'n': 14, 'mean': -0.5277673165363561}}; by link {'exact_clone': {'n': 25, 'mean': -0.6345084411068597}, 'token_only': {'n': 9, 'mean': -0.5332829978763403}}; by speed {'instant': {'n': 27, 'mean': -0.668366772945439}, 'slow': {'n': 7, 'mean': -0.3737650198616712}}; warm-up {'full_lookback': {'n': 33, 'mean': -0.6297132916169272}, 'warmup': {'n': 1, 'mean': 0.11828061480004436}}.
- host|N3h diagnostics: by tag {'cold|crowd': {'n': 156, 'mean': -0.16627580227905664}, 'cold|few': {'n': 287, 'mean': -0.45365187559103964}, 'hot|crowd': {'n': 35, 'mean': -0.2507191332164363}, 'hot|few': {'n': 30, 'mean': -0.5703184704368109}}; by link {'exact_clone': {'n': 309, 'mean': -0.38349364070831543}, 'token_only': {'n': 199, 'mean': -0.31920754897975545}}; by speed {'instant': {'n': 414, 'mean': -0.35205265923912393}, 'slow': {'n': 94, 'mean': -0.38587272660471783}}; warm-up {'full_lookback': {'n': 499, 'mean': -0.35441233018187285}, 'warmup': {'n': 9, 'mean': -0.5744538294540268}}.
- host|N12h diagnostics: by tag {'cold|crowd': {'n': 403, 'mean': -0.3283021470308546}, 'cold|few': {'n': 192, 'mean': -0.3887318575034078}, 'hot|crowd': {'n': 66, 'mean': -0.47439443730460423}, 'hot|few': {'n': 36, 'mean': -0.489995941735383}}; by link {'exact_clone': {'n': 502, 'mean': -0.37000812965266405}, 'token_only': {'n': 195, 'mean': -0.3597337824257897}}; by speed {'instant': {'n': 556, 'mean': -0.3721135784421854}, 'slow': {'n': 141, 'mean': -0.34749658897029256}}; warm-up {'full_lookback': {'n': 627, 'mean': -0.36454565420473756}, 'warmup': {'n': 70, 'mean': -0.3903149067470842}}.

## Exhaustion veto (the inverse, PREREG 6)

- host|N3h: host trades 508, flagged (hot) 65, unflagged 443; flagged mean -39.8%, unflagged mean -35.2%; by crowding {'few': {'flagged_mean': -0.5703184704368109, 'n_flagged': 30, 'unflagged_mean': -0.45365187559103964, 'n_unflagged': 287}, 'crowd': {'flagged_mean': -0.2507191332164363, 'n_flagged': 35, 'unflagged_mean': -0.16627580227905664, 'n_unflagged': 156}}; verdict **FAIL**.
- host|N12h: host trades 697, flagged (hot) 102, unflagged 595; flagged mean -48.0%, unflagged mean -34.8%; by crowding {'few': {'flagged_mean': -0.489995941735383, 'n_flagged': 36, 'unflagged_mean': -0.3887318575034078, 'n_unflagged': 192}, 'crowd': {'flagged_mean': -0.47439443730460423, 'n_flagged': 66, 'unflagged_mean': -0.3283021470308546, 'n_unflagged': 403}}; verdict **FAIL**.

## Decision

- **NO_CONFIG**.
- MOM mom|N3h|th0.25: n 65, keys 34, mean -39.8%, 90% CI key low -64.6%, placebo diff -3.3%, qualifies False.
- MOM mom|N3h|th1: n 25, keys 18, mean -51.5%, 90% CI key low -71.0%, placebo diff -14.8%, qualifies False.
- MOM mom|N12h|th0.25: n 102, keys 56, mean -48.0%, 90% CI key low -62.9%, placebo diff -11.3%, qualifies False.
- MOM mom|N12h|th1: n 34, keys 25, mean -60.8%, 90% CI key low -74.4%, placebo diff -22.0%, qualifies False.
- EXH N = 3 h: flagged 65, unflagged 443, flagged -39.8% vs unflagged -35.2%, CI95 hi +13.1%, qualifies False.
- EXH N = 12 h: flagged 102, unflagged 595, flagged -48.0% vs unflagged -34.8%, CI95 hi +3.4%, qualifies False.
- Shortlists written: False (branches []).
- powered MOM configs / vetoes failed their TRAIN bars
