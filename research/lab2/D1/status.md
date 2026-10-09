# D1 status

- version `d1-v1`, PREREG locked: False, trials so far: 2576

| split | usable | B1-eligible | with B1 | B2 complete |
|---|---:|---:|---:|---|
| train | 144 | 67 | 0 | False |
| val | 651 | 189 | 0 | False |
| test | 1264 | 418 | 0 | True |
| confirm | 0 | 0 | 0 | False |
| final_train | 450 | 152 | 0 | True |
| final_val | 150 | 37 | 0 | True |
| final_test | 163 | 43 | 0 | False |

| stage | state |
|---|---|
| train | prerequisites met (data checked at run time) |
| val | refused: no TRAIN run yet (D1/prereg_lock.json missing): run --stage train first |
| test | refused: no TRAIN run yet (D1/prereg_lock.json missing): run --stage train first |
| confirm | refused: no TRAIN run yet (D1/prereg_lock.json missing): run --stage train first |
| final | refused: no TRAIN run yet (D1/prereg_lock.json missing): run --stage train first |
