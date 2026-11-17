# PS1 (q7) debug (final_train)

Run 2026-10-09 04:31:36 UTC, 6.3 s. Version `ps1-v1`, PREREG sha256 `3fd6c46db70f`, common.py `22c560c51e2e`. Trials in the ledger: 2575. **Overall: PENDING (no official TRAIN run).**

**DEBUG (census TRAIN third): counts only. Returns, exit reasons and decisions are hidden.**

## Structure (coins, no outcomes)

- Usable coins: 450 over 0.52 days of creation.
- SFX0 (no `pump` suffix): 108 (24.0 %).
- CU known 429, CU true 28 (6.5 % of known).
- Instant: {'True': 277, 'False': 173}. Classes at g + 140 s: {'ORGANIC': 193, 'FACTORY': 183, 'OPERATOR': 34, 'UNRESOLVED': 21, 'COMPLETED': 19}.
- SFX0 by class: {'OPERATOR': {'n': 34, 'sfx0': 0}, 'FACTORY': {'n': 183, 'sfx0': 60}, 'COMPLETED': {'n': 19, 'sfx0': 5}, 'UNRESOLVED': {'n': 21, 'sfx0': 10}, 'ORGANIC': {'n': 193, 'sfx0': 33}}.
- SFX0 by instant: {'True': {'n': 277, 'sfx0': 63}, 'False': {'n': 173, 'sfx0': 45}, 'unknown': {'n': 0, 'sfx0': 0}}.
- CU by SFX0: {'sfx0': {'cu_true': 12, 'cu_false': 86, 'cu_unknown': 10}, 'pump': {'cu_true': 16, 'cu_false': 315, 'cu_unknown': 11}}.

## CU meaning check (PREREG 2.3, structure only)

- 28 CU coins of 429 known (share 6.5 %). Rule: withdraw config 4 if the CU share of known coins is < 2% or > 98%. Withdraw config 4: **False**.
- Summary: {'signers_on_1_coin': 26, 'signers_on_2plus_coins': 2, 'signer_is_another_coins_creator': 0, 'sfx0': 12, 'instant': 1, 'token_programs': {'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb': 27, 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA': 1}}.

| mint | signer coins | creator coins | signer is another coin's creator | SFX0 | grad delay s | token program | class |
|---|---:|---:|---|---|---:|---|---|
| `32nBFz2qd2…EBL6` | 1 | 1 | False | True | 278 | `TokenzQd…` | COMPLETED |
| `5mKtngpQ6e…pump` | 1 | 1 | False | False | 170 | `TokenzQd…` | ORGANIC |
| `HJnjwrGGjW…pump` | 1 | 1 | False | False | 429 | `TokenzQd…` | ORGANIC |
| `DDNtcencWK…pump` | 1 | 1 | False | False | 67 | `TokenzQd…` | ORGANIC |
| `C25KSH68Hb…pump` | 1 | 1 | False | False | 129 | `TokenzQd…` | ORGANIC |
| `2J8AGnaeNe…pump` | 1 | 1 | False | False | 147 | `TokenzQd…` | ORGANIC |
| `HvpfLzixvr…pump` | 1 | 1 | False | False | 53 | `TokenzQd…` | ORGANIC |
| `7aNVac2SMH…eo21` | 1 | 1 | False | True | 1391 | `TokenzQd…` | ORGANIC |
| `2CycCyG3e4…pump` | 1 | 1 | False | False | 497 | `TokenzQd…` | ORGANIC |
| `HvrpYb7U7B…pump` | 1 | 1 | False | False | 44 | `TokenzQd…` | ORGANIC |
| `7tweTogdr5…pump` | 1 | 1 | False | False | 62 | `TokenzQd…` | ORGANIC |
| `DZaQRdmPHN…Fvaz` | 1 | 1 | False | True | 1832 | `TokenzQd…` | ORGANIC |
| `7q3AVPhVMP…pump` | 1 | 1 | False | False | 58 | `TokenzQd…` | ORGANIC |
| `C111EjX9Ld…wQnH` | 1 | 1 | False | True | 312 | `TokenzQd…` | ORGANIC |
| `DE24kViq63…pump` | 1 | 1 | False | False | 66 | `TokenzQd…` | ORGANIC |
| `HCvCuULt6a…AQMW` | 1 | 1 | False | True | 5 | `Tokenkeg…` | ORGANIC |
| `3tA5zVRcfT…pump` | 1 | 1 | False | False | 2374 | `TokenzQd…` | ORGANIC |
| `Fz6mtRZohC…nJDQ` | 1 | 1 | False | True | 2374 | `TokenzQd…` | ORGANIC |
| `7eZcomYJAB…auG8` | 2 | 1 | False | True | 319 | `TokenzQd…` | ORGANIC |
| `9n2RHJYZDr…pump` | 1 | 1 | False | False | 119 | `TokenzQd…` | ORGANIC |

## Hosts

| Host | trades | per day | median decision age (min) | SFX0 | CU t/f/unknown | by class | mean | 95% CI | costs x1.5 | horizon exits |
|---|---:|---:|---:|---:|---|---|---:|---|---:|---:|
| R0 | 94 | 180.7 | 57.4 | 19 | 10/74/10 | {'ORGANIC': 29, 'OPERATOR': 29, 'FACTORY': 19, 'UNRESOLVED': 10, 'COMPLETED': 7} | n/a | n/a | n/a | 0 |
| R30 | 137 | 263.3 | 30.4 | 25 | 15/109/13 | {'ORGANIC': 46, 'FACTORY': 38, 'OPERATOR': 30, 'UNRESOLVED': 13, 'COMPLETED': 10} | n/a | n/a | n/a | 0 |

## Veto configs

| Config | eval set | unknown | flagged | unflagged | flagged/day | flagged mean | unflagged mean | diff [95% CI] | win profit removed | placebo p | in-sample veto |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| R0|SFX0|ALL | 94 | 0 | 19 | 75 | 36.5 | n/a | n/a | n/a n/a | n/a % | n/a | n/a |
| R0|SFX0|ORGANIC | 29 | 0 | 9 | 20 | 17.3 | n/a | n/a | n/a n/a | n/a % | n/a | n/a |
| R30|SFX0|ALL | 137 | 0 | 25 | 112 | 48.0 | n/a | n/a | n/a n/a | n/a % | n/a | n/a |
| R0|CU|ALL | 84 | 10 | 10 | 74 | 19.2 | n/a | n/a | n/a n/a | n/a % | n/a | n/a |

### By G1 class (flagged / unflagged)

- R0|SFX0|ALL: OPERATOR 0/29; FACTORY 1/18; COMPLETED 3/4; UNRESOLVED 6/4; ORGANIC 9/20
- R0|SFX0|ORGANIC: ORGANIC 9/20
- R30|SFX0|ALL: OPERATOR 0/30; FACTORY 1/37; COMPLETED 5/5; UNRESOLVED 7/6; ORGANIC 12/34
- R0|CU|ALL: OPERATOR 0/29; FACTORY 0/19; COMPLETED 1/6; ORGANIC 9/20

### Dose report (SFX0 x instant)

- R0|SFX0|ALL: sfx0|instant 2, sfx0|slow 17, sfx0|unknown 0, pump|instant 52, pump|slow 23, pump|unknown 0.
- R0|SFX0|ORGANIC: sfx0|instant 1, sfx0|slow 8, sfx0|unknown 0, pump|instant 5, pump|slow 15, pump|unknown 0.
- R30|SFX0|ALL: sfx0|instant 2, sfx0|slow 23, sfx0|unknown 0, pump|instant 75, pump|slow 37, pump|unknown 0.

## Decision

```
{
 "verdict": "DEBUG",
 "note": "mechanics and counts only; returns hidden"
}
```
