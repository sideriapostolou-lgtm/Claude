# Z5 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:50:38 UTC; runtime 148.5 s; PREREG sha256 `032126ee8360`; trials in the ledger: 2575.
- **Hosts:** R0 `27a79bc60126`; M1 m1-v1 `9c0a14afb895` (m1.py sha256 `b5489ac2686d`).
- **Overall Z5 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics, counts and decision-time costs only. Returns, exit reasons, fill prices and placebo outcomes are hidden, and no parameter was chosen here.**

## Host entry decisions and their quoted cost (no outcomes)

| host | entries | per day | decision rt | decision mcap (SOL) | fee tier at decision (bps: n) |
|---|---:|---:|---|---|---|
| R0 | 94 | 180.7 | median 3.29% (IQR 1.79%-3.73%, n 94) | median 1,956 (IQR 334-67,471, n 94) | {'30.0': 15, '35.0': 1, '40.0': 1, '42.5': 1, '45.0': 6, '50.0': 1, '70.0': 1, '80.0': 4, '85.0': 1, '90.0': 4, '95.0': 5, '100.0': 4, '110.0': 1, '115.0': 8, '120.0': 14, '125.0': 27} |
| M1 | 24 | 46.1 | median 1.76% (IQR 1.44%-1.96%, n 24) | median 69,129 (IQR 55,219-1,096,115, n 24) | {'30.0': 9, '35.0': 1, '42.5': 1, '45.0': 3, '47.5': 3, '50.0': 1, '70.0': 1, '80.0': 4, '85.0': 1} |

| host | c | kept (quoted) | kept share | ex-ante saving (quoted rt) | filtered trades | subset of host |
|---|---|---:|---:|---:|---:|---|
| R0 | c3.40 | 53 | +56.4% | +0.67% | 53 | True |
| R0 | c3.00 | 44 | +46.8% | +0.88% | 44 | True |
| M1 | c3.40 | 24 | +100.0% | +0.00% | 24 | True |
| M1 | c3.00 | 24 | +100.0% | +0.00% | 24 | True |
- R0: PLAN 4.2 class at the entry decision, by quoted round trip: {'3.00-3.40%': {'OTHER': 5, 'FACTORY': 4}, 'rt <= 3.00%': {'OPERATOR': 29, 'FACTORY': 13, 'OTHER': 2}, 'rt > 3.40%': {'OTHER': 39, 'FACTORY': 2}}.
- M1: PLAN 4.2 class at the entry decision, by quoted round trip: {'rt <= 3.00%': {'OPERATOR': 24}}.
- R0 guard config: 53 trades; same entries as the c3.40 host-exit config: True.
- M1 guard config: 24 trades; same entries as the c3.40 host-exit config: True.

## Configs

| config | trades | coins | class at decision | operator clusters | largest cluster trades | placebo trades | controls | horizon exits | entries/day |
|---|---:|---:|---|---:|---:|---:|---|---:|---:|
| R0|c-none|hx | 94 | 94 | {'OTHER': 46, 'OPERATOR': 29, 'FACTORY': 19} | 29 | 66 | 1880 | {'class_matched': 1472} | 0 | 180.7 |
| R0|c3.40|hx | 53 | 53 | {'OPERATOR': 29, 'FACTORY': 17, 'OTHER': 7} | 21 | 33 | 1060 | {'class_matched': 709, 'cost_band': 1002} | 0 | 101.9 |
| R0|c3.00|hx | 44 | 44 | {'OPERATOR': 29, 'FACTORY': 13, 'OTHER': 2} | 15 | 30 | 880 | {'class_matched': 562, 'cost_band': 809} | 0 | 84.6 |
| R0|c3.40|guard | 53 | 53 | {'OPERATOR': 29, 'FACTORY': 17, 'OTHER': 7} | 21 | 33 | 1060 | {'class_matched': 709, 'cost_band': 1002} | 0 | 101.9 |
| M1|c-none|hx | 24 | 24 | {'OPERATOR': 24} | 1 | 24 | 300 | {'unmatched': 480} | 0 | 46.1 |
| M1|c3.40|hx | 24 | 24 | {'OPERATOR': 24} | 1 | 24 | 300 | {'unmatched': 480, 'cost_band': 300} | 0 | 46.1 |
| M1|c3.00|hx | 24 | 24 | {'OPERATOR': 24} | 1 | 24 | 300 | {'unmatched': 480, 'cost_band': 300} | 0 | 46.1 |
| M1|c3.40|guard | 24 | 24 | {'OPERATOR': 24} | 1 | 24 | 300 | {'unmatched': 480, 'cost_band': 300} | 0 | 46.1 |

## Decision

- **DEBUG**.
- mechanics, counts and decision-time costs only; returns hidden
