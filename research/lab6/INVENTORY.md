# Lab 6 inventory: Polymarket sports game moneylines and their Pinnacle match

Written by `run.py --inventory` 2026-10-09T21:55:30+00:00. Source: lab 4's cache (markets closed 2026-07-01 -> 2026-10-09, volume >= $20k, tapes = the last 14 days before resolution).

- lab 4 sports markets: 42,124 in 20,344 events
- game moneyline markets (2-way `A vs. B`, or soccer `Will X win on <date>?` / `... end in a draw?`): 20,014 in 16,710 games (13,227 2-way, 3,483 soccer 3-way); every market resolved cleanly (one winner) in 16,412 games (the rest have a 50/50 split resolution, settled at 0.5)
- in a league The Odds API covers with Pinnacle (PLAN §1 table): 6,234 games; with at least one print in the 24 h before the scheduled start: 6,167
- active (scheduled start known, a tape for every market, prints before the start): 6,167
- **matched to a Pinnacle event: 5,476 (88.8 %)**; by split {'val': 2272, 'train': 2161, 'test': 1043}; median |Pinnacle commence - Polymarket gameStartTime| 0.0 min
- Pinnacle table: 216,507 rows, 7,224 events, 23,543 (sport, snapshot) pairs
- data verdict: **OK** (the bar: at least 500 matched games with prints)

Failures (active games not matched), by reason:

- no Pinnacle event near the start time: 284
- no Pinnacle events for the sport keys: 221
- team names do not match: 184

Examples of failures:

| game | league | reason | Polymarket teams | best Pinnacle candidate |
|---|---|---|---|---|
| atp-alcaraz-lehecka-2026-10-06 | atp | no Pinnacle event near the start time | Carlos Alcaraz / Jiri Lehecka | - |
| atp-basavar-schoolk-2026-08-30 | atp | team names do not match | Nishesh Basavareddy / Tristan Schoolkate | Francisco Comesana vs Flavio Cobolli (sim 0.375) |
| atp-bellucc-piros-2026-08-30 | atp | team names do not match | Mattia Bellucci / Zsombor Piros | Francisco Comesana vs Flavio Cobolli (sim 0.194) |
| atp-bergs-taberne-2026-08-30 | atp | team names do not match | Zizou Bergs / Carlos Taberner | Matteo Berrettini vs Mariano Navone (sim 0.357) |
| atp-bublik-machac-2026-10-09 | atp | team names do not match | Alexander Bublik / Tomas Machac | Novak Djokovic vs Hubert Hurkacz (sim 0.308) |
| atp-djokovi-minaur-2026-10-06 | atp | no Pinnacle event near the start time | Novak Djokovic / Alex de Minaur | - |
| atp-gorzny-collign-2026-08-30 | atp | team names do not match | Sebastian Gorzny / Raphael Collignon | Brandon Nakashima vs Sebastian Baez (sim 0.412) |
| atp-jodar-busta-2026-07-01 | atp | team names do not match | Rafael Jodar / Pablo Carreno Busta | Matteo Berrettini vs Arthur Fils (sim 0.333) |
| atp-zverev-shelton-2026-09-13 | atp | no Pinnacle event near the start time | Alexander Zverev / Ben Shelton | - |
| bknbl-bri-new-2026-09-22 | bknbl | no Pinnacle event near the start time | Brisbane Bullets / New Zealand Breakers | - |
| bknbl-cai-tas-2026-09-23 | bknbl | no Pinnacle event near the start time | Cairns Taipans / Tasmania JackJumpers | - |
| bknbl-mel-ade-2026-09-19 | bknbl | no Pinnacle event near the start time | Melbourne United / Adelaide 36ers | - |
| col-aek-bei-2026-07-23 | col | no Pinnacle events for the sport keys | - | - |
| col-aja-she1-2026-08-06 | col | no Pinnacle events for the sport keys | - | - |
| col-aja-sio-2026-08-27 | col | no Pinnacle events for the sport keys | - | - |
| col-aja-vns-2026-07-30 | col | no Pinnacle events for the sport keys | - | - |
| col-al-bra-2026-08-11 | col | no Pinnacle events for the sport keys | - | - |
| col-al-dil-2026-07-28 | col | no Pinnacle events for the sport keys | - | - |

By league (games = game moneylines in lab 4's cache):

| league | games | covered | clean | active | matched |
|---|---|---|---|---|---|
| atp | 3726 | 529 | 3657 | 512 | 486 |
| cs2 | 1979 | 0 | 1886 | 0 | 0 |
| wta | 1836 | 585 | 1794 | 583 | 558 |
| mlb | 1185 | 1185 | 1184 | 1183 | 1180 |
| itf | 1092 | 0 | 1072 | 0 | 0 |
| lol | 1037 | 0 | 1027 | 0 | 0 |
| dota2 | 439 | 0 | 413 | 0 | 0 |
| val | 398 | 0 | 398 | 0 | 0 |
| ufc | 211 | 211 | 203 | 205 | 203 |
| col | 203 | 203 | 203 | 203 | 0 |
| wnba | 202 | 202 | 202 | 202 | 194 |
| mls | 184 | 184 | 184 | 184 | 184 |
| arg | 150 | 150 | 150 | 150 | 150 |
| crint | 145 | 124 | 139 | 120 | 53 |
| cfb | 137 | 137 | 137 | 133 | 90 |
| bra | 111 | 111 | 111 | 107 | 107 |
| unl | 104 | 104 | 104 | 104 | 32 |
| ucl | 104 | 104 | 104 | 104 | 32 |
| bra2 | 101 | 101 | 101 | 99 | 99 |
| uel | 98 | 98 | 98 | 98 | 18 |
| clf | 96 | 0 | 96 | 0 | 0 |
| col1 | 94 | 0 | 94 | 0 | 0 |
| kbo | 91 | 91 | 87 | 89 | 79 |
| nhl | 87 | 87 | 87 | 77 | 55 |
| mex | 86 | 86 | 86 | 86 | 86 |
| kor | 77 | 77 | 77 | 75 | 75 |
| chi | 75 | 75 | 75 | 75 | 75 |
| nbasl | 74 | 74 | 74 | 74 | 74 |
| lal | 69 | 69 | 69 | 69 | 69 |
| nfl | 68 | 68 | 66 | 67 | 67 |
| swe | 68 | 68 | 68 | 68 | 68 |
| jap | 68 | 68 | 68 | 66 | 66 |
| elc | 66 | 66 | 66 | 66 | 66 |
| nor | 62 | 62 | 62 | 62 | 62 |
| lec | 61 | 61 | 61 | 61 | 61 |
| spl | 55 | 55 | 55 | 55 | 53 |
| es2 | 54 | 54 | 54 | 54 | 54 |
| ere | 54 | 54 | 54 | 54 | 54 |
| por | 53 | 53 | 53 | 53 | 53 |
| fif | 53 | 0 | 53 | 0 | 0 |
| epl | 50 | 50 | 50 | 50 | 50 |
| conl | 50 | 0 | 50 | 0 | 0 |
| sea | 50 | 50 | 50 | 50 | 50 |
| efl | 48 | 48 | 48 | 48 | 48 |
| bl2 | 47 | 47 | 47 | 47 | 47 |
| den | 46 | 46 | 46 | 46 | 46 |
| fl1 | 44 | 44 | 44 | 44 | 44 |
| per1 | 44 | 0 | 44 | 0 | 0 |
| tur | 43 | 43 | 43 | 43 | 43 |
| crict20blast | 39 | 39 | 38 | 39 | 38 |
| sud | 39 | 39 | 39 | 39 | 37 |
| bun | 36 | 36 | 36 | 36 | 36 |
| criccpl | 33 | 33 | 33 | 33 | 26 |
| chi1 | 33 | 33 | 33 | 33 | 32 |
| rou1 | 32 | 0 | 32 | 0 | 0 |
| crichundred | 32 | 32 | 32 | 32 | 32 |
| egy1 | 31 | 0 | 31 | 0 | 0 |
| euroleague | 31 | 31 | 31 | 31 | 30 |
| crichundredw | 30 | 30 | 28 | 30 | 23 |
| bel1 | 29 | 29 | 29 | 29 | 29 |
| cricetpl | 28 | 0 | 26 | 0 | 0 |
| bkfibaw | 26 | 0 | 26 | 0 | 0 |
| scop | 26 | 26 | 26 | 26 | 26 |
| sui | 26 | 26 | 26 | 26 | 26 |
| ecu1 | 26 | 0 | 26 | 0 | 0 |
| fifwc | 26 | 26 | 26 | 26 | 26 |
| cricodc | 25 | 0 | 25 | 0 | 0 |
| lib | 24 | 24 | 24 | 24 | 24 |
| nba | 24 | 24 | 24 | 17 | 17 |
| uwcl | 24 | 24 | 24 | 24 | 18 |
| brco | 24 | 0 | 24 | 0 | 0 |
| el1 | 24 | 24 | 24 | 24 | 24 |
| crict20lpl | 23 | 0 | 22 | 0 | 0 |
| bknbl | 23 | 23 | 23 | 22 | 15 |
| itc | 21 | 21 | 21 | 21 | 21 |
| pol | 21 | 21 | 21 | 21 | 21 |
| fin1 | 21 | 21 | 21 | 21 | 21 |
| bkfibaqeu | 20 | 0 | 20 | 0 | 0 |
| fr2 | 20 | 20 | 20 | 20 | 20 |
| bol1 | 20 | 0 | 20 | 0 | 0 |
| ja2 | 19 | 0 | 19 | 0 | 0 |
| cze1 | 19 | 0 | 19 | 0 | 0 |
| npb | 18 | 18 | 17 | 18 | 17 |
| dfb | 18 | 18 | 18 | 18 | 0 |
| itsb | 18 | 18 | 18 | 18 | 18 |
| afcq | 17 | 0 | 17 | 0 | 0 |
| argpn | 17 | 0 | 17 | 0 | 0 |
| rus | 16 | 16 | 16 | 16 | 16 |
| aut | 16 | 16 | 16 | 16 | 16 |
| cricmlc | 16 | 0 | 16 | 0 | 0 |
| acle | 15 | 0 | 15 | 0 | 0 |
| nwsl | 15 | 0 | 15 | 0 | 0 |
| daviscup | 15 | 0 | 7 | 0 | 0 |
| bkfibaqas | 15 | 0 | 15 | 0 | 0 |
| codmw | 14 | 0 | 14 | 0 | 0 |
| cricgsl | 12 | 0 | 12 | 0 | 0 |
| ukr1 | 12 | 0 | 12 | 0 | 0 |
| ned2 | 11 | 0 | 11 | 0 | 0 |
| auc | 10 | 0 | 10 | 0 | 0 |
| uzb1 | 10 | 0 | 10 | 0 | 0 |
| chi2 | 10 | 0 | 10 | 0 | 0 |
| swe2 | 9 | 9 | 9 | 9 | 9 |
| tur2 | 9 | 0 | 9 | 0 | 0 |
| col2 | 9 | 0 | 9 | 0 | 0 |
| argcopa | 9 | 0 | 9 | 0 | 0 |
| r6siege | 9 | 0 | 9 | 0 | 0 |
| asean | 8 | 0 | 8 | 0 | 0 |
| irl1 | 8 | 8 | 8 | 8 | 8 |
| hr1 | 7 | 0 | 7 | 0 | 0 |
| cfl | 7 | 7 | 7 | 7 | 6 |
| skc | 6 | 0 | 6 | 0 | 0 |
| isr | 6 | 0 | 6 | 0 | 0 |
| hun | 6 | 0 | 6 | 0 | 0 |
| uru1 | 6 | 0 | 6 | 0 | 0 |
| bra3 | 6 | 0 | 6 | 0 | 0 |
| bkfibaqam | 6 | 0 | 6 | 0 | 0 |
| wsl | 6 | 0 | 6 | 0 | 0 |
| cricdpl | 5 | 0 | 5 | 0 | 0 |
| kor2 | 5 | 0 | 5 | 0 | 0 |
| uae1 | 5 | 0 | 5 | 0 | 0 |
| u20wwc | 5 | 0 | 5 | 0 | 0 |
| bkfibaqaf | 5 | 0 | 5 | 0 | 0 |
| hok | 5 | 0 | 5 | 0 | 0 |
| zuffa | 4 | 4 | 4 | 4 | 3 |
| gre1 | 4 | 4 | 4 | 4 | 4 |
| boxing | 3 | 3 | 3 | 2 | 1 |
| el2 | 3 | 3 | 3 | 3 | 3 |
| afl | 1 | 1 | 1 | 1 | 1 |
| rlnrl | 1 | 1 | 1 | 1 | 1 |
