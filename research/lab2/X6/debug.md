# X6 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:32:20 UTC; runtime 6.2 s; PREREG sha256 `6f28eb52bb60`; trials in the ledger: 2575.
- **Overall X6 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, gate labels, exit reasons and fill prices are hidden and no parameter was chosen here.**

## Separation gate (PREREG 7)

- Observations: 171 from 96 coins (need ≥ 30 TAKEOVER and ≥ 30 DIES coins per K).
- Decision: **HIDDEN (debug split: no outcome statistics)**.

| K | obs | TAKEOVER | REPLACE | DIES | MIDDLE | momentum |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 96 | 6 | 5 | 38 | 52 | 30 |
| 10 | 75 | 4 | 4 | 31 | 40 | 31 |

## Event counts and structure (no returns)

- Coins 450; universe funnel: {'instant': 277, 'in_universe': 173}.
- BOOST's last bar j_b (all coins with an AGENT bar): {'5': 155, '6': 290, '7': 5}; baseline bars (universe): {'3': 40, '4': 128, '5': 5}.
- BOOST-time non-AGENT buy SOL/min: {'p10': 1.094615095833333, 'p25': 8.3937466125, 'p50': 23.9515142725, 'p75': 61.56153474749999, 'p90': 136.19305466540015}; buyers/min: {'p10': 4.0, 'p25': 19.25, 'p50': 62.5, 'p75': 152.0, 'p90': 224.2000000000001}.

| K | decisions | alive | TAKEOVER CONSTANT | TAKEOVER REPLACE | DIES | MIDDLE | momentum | past g+25 | decision age (min) | r_P / r_org_B |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 5 | 173 | 96 | 6 | 5 | 38 | 52 | 30 | 0 | {'p10': 11.166666666666666, 'p50': 11.6, 'p90': 12.08} | {'p10': 0.20008535124485757, 'p25': 0.36309344050432085, 'p50': 0.6048709793298461, 'p75': 0.8698955994107704, 'p90': 1.4861128310457214} |
| 10 | 173 | 75 | 4 | 4 | 31 | 40 | 31 | 0 | {'p10': 16.166666666666668, 'p50': 16.6, 'p90': 17.08} | {'p10': 0.1615702722631397, 'p25': 0.3021066580555457, 'p50': 0.567281532390568, 'p75': 0.866265414341544, 'p90': 1.3908416518127107} |

| K | rate_CONSTANT | rate_REPLACE | size | absorb | breadth | dispersed | alive |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 21 | 16 | 126 | 41 | 22 | 99 | 96 |
| 10 | 13 | 8 | 122 | 41 | 19 | 116 | 75 |

## Configs

| config | trades | coins | decision age (min) | r_P / r_org_B | nb_P | placebo trades | controls | horizon exits | entries/day |
|---|---:|---:|---|---|---|---:|---|---:|---:|
| K5|hold30 | 6 | 6 | {'p10': 11.341666666666667, 'p50': 11.833333333333334, 'p90': 11.983333333333334} | {'p10': 1.0779749337267686, 'p50': 1.2381294403521577, 'p90': 1.8748566783160405} | {'p10': 48.1, 'p50': 157.4, 'p90': 262.2} | 120 | {'momentum': 113, 'unmatched': 120} | 0 | 11.5 |
| K5|fade60 | 6 | 6 | {'p10': 11.341666666666667, 'p50': 11.833333333333334, 'p90': 11.983333333333334} | {'p10': 1.0779749337267686, 'p50': 1.2381294403521577, 'p90': 1.8748566783160405} | {'p10': 48.1, 'p50': 157.4, 'p90': 262.2} | 120 | {'momentum': 113, 'unmatched': 120} | 0 | 11.5 |
| K10|hold30 | 4 | 4 | {'p10': 16.436666666666667, 'p50': 16.708333333333336, 'p90': 17.003333333333334} | {'p10': 1.2767527221631545, 'p50': 1.6596478212049992, 'p90': 9.374523479562088} | {'p10': 56.30000000000001, 'p50': 197.85, 'p90': 231.32000000000002} | 80 | {'momentum': 65, 'unmatched': 80} | 0 | 7.7 |
| K10|fade60 | 4 | 4 | {'p10': 16.436666666666667, 'p50': 16.708333333333336, 'p90': 17.003333333333334} | {'p10': 1.2767527221631545, 'p50': 1.6596478212049992, 'p90': 9.374523479562088} | {'p10': 56.30000000000001, 'p50': 197.85, 'p90': 231.32000000000002} | 80 | {'momentum': 65, 'unmatched': 80} | 0 | 7.7 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
