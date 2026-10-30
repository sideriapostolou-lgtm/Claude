# H2 closing-line value: does the entry price beat Pinnacle's last pre-game line (diagnostic): TRAIN (train, lab6-v1)

Run 2026-10-09T21:56:50+00:00. No-skill baseline (PLAN §3, H2): every side of every matched game bought at the first buyable print (big enough for the ticket) once the window opens, at print + one tick; CLV = Pinnacle's closing no-vig fair (multiplicative) - price paid. The strategy's own CLV is in H1's table.

| window | sides | games | mean CLV (pts) | CLV CI95 | beat close | mean abs gap | mean net | net CI95 |
|---|---|---|---|---|---|---|---|---|
| W24h | 5813 | 2130 | -0.0119 | [-0.0122, -0.0116] | 0.305 | 0.0267 | -0.0265 | [-0.0436, -0.0072] |
| W6h | 5716 | 2120 | -0.0127 | [-0.0130, -0.0125] | 0.241 | 0.0216 | -0.0274 | [-0.0459, -0.0098] |
| W1h | 5228 | 2029 | -0.0125 | [-0.0128, -0.0123] | 0.170 | 0.0174 | -0.0213 | [-0.0399, -0.0021] |

Diagnostic only: H2 selects nothing and decides nothing.
