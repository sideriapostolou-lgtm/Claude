# Polymarket US venue map: what the desk trades, and whether history can judge it

Written 2026-10-10 ~18:40 UTC. Research only: nothing here trades, no key was used, every number comes from a file
listed at the end. The machine-readable version is `venue_map.json` (built by `venue_map_build.py`); look up any slug
by its first two words in `by_slug_prefix` (for example `aec-setkameua`).

Paper (pretend money) and real money are kept apart everywhere. A split of our own 7 real losses is a description of
where they happened, not proof that a filter works; only history (lab 4: TRAIN selects, VAL confirms, TEST one look)
can prove that. Two things below need no proof, because they are arithmetic or the lab's own standing rule: buying
two outcomes of one game, and real money where there is no history at all.

## The answer in plain words

1. **The real losses sit where nothing can check the price.** 34 of the 91 real bets were in leagues that the
   polymarket.com history has never seen (Setka Cup table tennis, eBattles e-soccer, German DEL hockey and others).
   Those 34 hold **-$4.14 of the -$4.89** total. The other 57 real bets lost $0.74 together; the 10 ATP and WTA
   tennis bets (the only real losers that history *can* judge) lost $1.79 of it.
2. **e-soccer books are often impossible.** An eBattles game has three YES/NO contracts (home win, draw, away win);
   exactly one pays $1. On 2026-10-09, 15 of 96 recorded e-soccer games showed the three YES bids adding up to more
   than $1.02, and 24 showed two or three outcomes "near-certain" at once. On 2026-10-10 at 18:18 UTC five e-soccer games
   about to start had **all three outcomes priced 0.97-0.99**. The desk bought all three outcomes of Sassuolo vs
   Roma at 0.98 each on 2026-10-10 13:12 UTC: $2.94 paid for a game that pays $1. Real soccer (83 games recorded) showed
   none of this.
3. **German DEL hockey is a market almost nobody trades on this venue.** The median DEL winner market traded **$48
   over its whole life** (6 markets), with a typical bid/ask gap of 0.30 during play. A "0.95" there is one person's
   order, not a crowd's belief. Both real DEL bets (adopted from the venue on 2026-10-09, older looser rule, one at
   0.95) lost.
4. **Half the venue cannot be judged on history.** Of the 2,646 game-winner markets listed for the next 24 hours,
   1,289 (49 %) are in leagues with **no** polymarket.com history, 438 (17 %) in leagues with fewer than 30 games, 386
   (15 %) in leagues with history but no recorded game end (ITF tennis, esports, UFC, KBO), 365 (14 %) "some", and only
   168 (6 %) in leagues with 30+ TRAIN games with a recorded end (the bar lab 4 P6 uses for a sport).
5. **Paper and real ran at different hours, so on different sports.** The paper book's 73 wins of 73 (current rule,
   $20 pretend tickets, +$29.79) were bought 22:29-05:12 UTC (crypto, Americas soccer, e-soccer, esports). Real money
   started 05:05 UTC and bought 05:17-13:14 UTC, when the venue is mostly ITF/ATP/WTA tennis and Setka Cup table
   tennis. And **47 of the 73 paper wins were "short" buys** (the NO side, bought at 1 minus the bid), which real
   money never makes (live mode buys the YES side only); only 26 were the YES buys the real desk makes. The two
   records are not two looks at the same thing.
6. **Safe moves that only buy less** (for the desk owner to decide; this map changes no code):
   never buy a second outcome of a game the desk already holds; skip any 3-way game whose three YES bids add up to
   more than $1; no real money in leagues with no history (the lab rule "no proof = no real money"); require the
   event's own `live` flag. Details in "What this means" below.

## How to read a slug

The first word of every Polymarket US slug says what kind of contract it is; the second word is the league code.
Read off the gateway's own `marketType` / `sportsMarketTypeV2` for all 33,934 sports markets of the 1,534 events
listed at 18:18 UTC (live, or starting in the next 24 h).

| prefix | what it is | listed now | does the desk buy it? |
|---|---|---|---|
| `aec-` | two-way game winner (either team / player); type MONEYLINE | 969 | **yes**, in play |
| `atc-` | YES/NO team contract: in soccer and e-soccer the three legs of the result (home win / draw / away win; type DRAWABLE_OUTCOME, 1,677); elsewhere props such as "wins the 4th quarter" (type PROP, 2,521) | 4,198 | **yes** for the soccer / e-soccer legs, no for props |
| `asc-` | spreads (handicaps) | 7,817 | no |
| `tsc-` | totals, over / under | 8,510 | no |
| `astatc-` | player and game stat props | 12,319 | no |
| `tec-`, `arankc-`, `aachc-` | futures (race winner, top-3, fastest lap) | 121 | no |
| `cpc-` | crypto price contracts (`cpc-btc-...`) | (non-sports) | yes, last hour |
| `tc-` | weather contracts (`tc-temp-...` city highs) | (non-sports) | yes, last hour |

So `aec-setkameua-...` is a Setka Cup Ukraine table-tennis match winner, `atc-ebfsa-sas-roma-...-dh4-draw` is the
"draw" leg of an eBattles e-soccer Serie A game (`dh4` tells apart repeat meetings of the same two teams that day), `aec-del-...` a German
DEL hockey game, `aec-itfme-` / `aec-itfwo-` ITF men / women tennis.

**Code traps** (the US codes and polymarket.com codes do not always mean the same thing):

- US `srb` is the **Italian** Serie B; polymarket.com `srb` is the **Serbian** league. History is read from `itsb`.
- US `irl1` is the League of Ireland **First** Division; polymarket.com `irl1` is the **Premier** Division (US `irlp`).
- US `pdc` is Chilean football; US `pdcdarts` is darts. US `bbl` is German basketball, not cricket's Big Bash.
- polymarket.com `itf` mixes men and women; before September its titles do not say which, so the map reads the
  rules text (`M15` / `M25` vs `W15`-`W100`).
- Many codes differ: Ligue 1 is `lg1` (US) / `fl1` (.com), Liga Portugal `ligpor` / `por`, EFL Championship `eflch` /
  `elc`, 2. Bundesliga `bun2` / `bl2`, J1 `j1` / `jap`, K League 1 `kl1` / `kor`, Chinese Super League `csl` / `chi`,
  Ekstraklasa `ekst` / `pol`, and so on; all 169 are in the JSON.

## How the desk picks games (`polydesk.live_sports_markets`)

1. Ask the gateway for open sports events that started in the last 12 hours (up to 5 pages of 100).
2. Keep an event only if its start time has passed and its `period` is not one of
   `NS, "", CAN, SUS, PST, FT, AOT, FINAL, ENDED`.
3. Keep its markets whose type contains `MONEYLINE` or `DRAWABLE_OUTCOME` (the `aec-` winners and the soccer /
   e-soccer `atc-` legs) and that are not closed.
4. Sort by game start, **newest first**, and keep the first `SPORTS_CAP` = 150.

What that gave at 18:18 UTC: 214 events in the query, 178 live winner markets, **150 kept, 28 cut**. The cut ones are
the oldest games, i.e. the ones nearest their end (college football in the 3rd/4th quarter, Swedish hockey in the 3rd
period, tennis in a 3rd set), started 2.3 to 8.3 hours earlier; 3 of those 28 passed the buy test at that moment
against 5 of the 150 kept. Each soccer game takes three of the 150 places (one per leg): the 150 were 78 soccer legs,
25 college football, 15 basketball, 8 esports, 7 hockey, 6 table tennis, 6 e-soccer, 4 tennis, 1 darts.

Two gaps in how the list is read:

- the event's own `live` and `ended` flags are never read, only the period word. A postponed VTB basketball game
  (`period` = `POST`, `live` = false) passed the desk's in-play test at 18:18 (the cap then cut it); `VFT`, `END Q4`
  and `LIVE` also count as in play. This cost nothing so far;
- each market is judged on its own: nothing compares the three legs of a soccer / e-soccer game, and nothing stops
  a second buy in a game the desk already holds. This is what cost $1.94 at 13:12.

## Real record by sport, and by how much history exists

Real money since 2026-10-09 (91 settled, 84 won, -$4.89; one contract per bet). Paper = the current rule's paper book
($20 pretend tickets, bought 2026-10-09 22:29 .. 2026-10-10 05:12 UTC; in live mode paper buys nothing; 47 of its 73
buys were NO-side "shorts" that real money cannot make).

| sport | real bets | won | real $ | paper (current rule) bets / won | game-winner markets next 24 h | history games (>= 50 fills) |
|---|---|---|---|---|---|---|
| tennis | 28 | 26 | -1.38 | 7 / 7 | 436 | 5,987 |
| e-soccer | 4 | 2 | -1.93 | 8 / 8 | 66 | 0 |
| ice hockey | 2 | 0 | -1.93 | 2 / 2 | 54 | 79 |
| table tennis | 17 | 16 | -0.54 | 7 / 7 | 155 | 1 |
| soccer | 10 | 10 | +0.24 | 13 / 13 | 1,611 | 2,150 |
| basketball | 6 | 6 | +0.13 | 1 / 1 | 103 | 280 |
| esports | 3 | 3 | +0.07 | 7 / 7 | 56 | 3,731 |
| baseball | 1 | 1 | +0.02 | 0 | 5 | 1,284 |
| crypto (non-sports) | 20 | 20 | +0.43 | 23 / 23 | - | - |
| american football, cricket, others | 0 | - | - | 5 / 5 | 160 | - |

| history level of the league | what it means | real bets | won | real $ | share of next-24h winner markets |
|---|---|---|---|---|---|
| none | not one game in the polymarket.com history | 34 | 29 | **-4.14** | 1,289 (49 %) |
| thin | 1-29 games | 5 | 5 | +0.13 | 438 (17 %) |
| no recorded end | 30+ games, but history never records when the game ended (P6 can only ever *block* these) | 20 | 20 | +0.46 | 386 (15 %) |
| some | 30+ games, fewer than 30 in TRAIN with a recorded end | 1 | 1 | +0.02 | 365 (14 %) |
| judgeable | 30+ TRAIN games with a recorded end | 11 | 9 | -1.78 | 168 (6 %) |
| non-sports | crypto (P4 territory) | 20 | 20 | +0.43 | - |

Every row is far too small to prove anything about a league by itself: at the prices paid (mean 0.975) the 91 bets
should lose about 2.3 times by price alone; we lost 7.

## Every league the desk has bought (real or paper)

History = polymarket.com game-winner games with at least 50 fills (in brackets: TRAIN games with a recorded end).
"$ traded" = median dollars traded over the whole life of one settled winner market on Polymarket US (gateway book
stats; n markets in brackets; n = 1-3 is one game, read it lightly). "Spread" = median ask minus bid while in play
(2026-10-09 recorder). Real = bets / won / dollars. Sorted by real dollars, worst first.

| US code | league | sport | shape | history games (TRAIN w/ end) | level | $ traded (n) | spread | real | paper (current rule) | warning signs |
|---|---|---|---|---|---|---|---|---|---|---|
| ebfsa | eBattles e-soccer: Serie A | e-soccer | 3-way | 0 (0) | none | $39 (90) | 0.030 | 3/1 -1.94 | 3/3 | made-for-betting, impossible 3-way books, thin |
| del | DEL (Germany) | ice hockey | 2-way | 0 (0) | none | $48 (6) | 0.295 | 2/0 -1.93 | - | thin |
| wta | WTA Tour (incl. WTA 125) | tennis | 2-way | 1,798 (787) | judgeable | $156,197 (9) | 0.010 | 4/3 -0.93 | 3/3 | - |
| atp | ATP Tour and Challenger | tennis | 2-way | 3,641 (1,431) | judgeable | $129,853 (17) | 0.010 | 6/5 -0.85 | 1/1 | - |
| setkameua | Setka Cup Ukraine, men | table tennis | 2-way | 0 (0) | none | $16,662 (78) | 0.010 | 16/15 -0.56 | 6/6 | made-for-betting |
| csl | Chinese Super League | soccer | 3-way | 75 (50) | judgeable | $7,358 (1) | - | 1/1 +0.01 | - | - |
| cznbl | NBL (Czechia) | basketball | 2-way | 0 (0) | none | $6,924 (2) | - | 1/1 +0.01 | - | - |
| ebfwcb | eBattles e-soccer: World Cup B | e-soccer | 3-way | 0 (0) | none | $54 (43) | 0.070 | 1/1 +0.01 | - | made-for-betting, impossible 3-way books, thin |
| bun2 | 2. Bundesliga | soccer | 3-way | 47 (15) | some | $11,553 (7) | 0.010 | 1/1 +0.02 | - | - |
| denbl | Basketligaen (Denmark) | basketball | 2-way | 0 (0) | none | $9,066 (1) | - | 1/1 +0.02 | - | - |
| dota2 | Dota 2 | esports | 2-way | 427 (0) | no recorded end | $19,661 (3) | 0.010 | 1/1 +0.02 | - | - |
| kbo | KBO (Korea) | baseball | 2-way | 85 (0) | no recorded end | $63,179 (1) | - | 1/1 +0.02 | - | - |
| setkamecz | Setka Cup Czechia, men | table tennis | 2-way | 1 (0) | thin | $8,121 (20) | 0.010 | 1/1 +0.03 | - | made-for-betting |
| bsl | Basketbol Super Ligi (Turkey) | basketball | 2-way | 0 (0) | none | $10,166 (1) | - | 1/1 +0.03 | - | - |
| den1 | Danish 1st Division | soccer | 3-way | 0 (0) | none | $2,019 (7) | 0.010 | 1/1 +0.03 | - | - |
| ekst | Ekstraklasa (Poland) | soccer | 3-way | 21 (0) | thin | $1,470 (6) | 0.010 | 1/1 +0.03 | - | - |
| j1 | J1 League (Japan) | soccer | 3-way | 66 (0) | no recorded end | $40,194 (1) | - | 1/1 +0.03 | - | - |
| j2 | J2 League (Japan) | soccer | 3-way | 17 (0) | thin | $22,853 (1) | - | 1/1 +0.03 | - | - |
| uwwcq | UEFA Women's World Cup qualifying | soccer | 3-way | 0 (0) | none | $895 (42) | 0.020 | 1/1 +0.03 | - | thin |
| wtadb | WTA doubles | tennis | 2-way | 0 (0) | none | $9,358 (1) | - | 1/1 +0.03 | - | - |
| ykk | Ykkosliiga (Finland, 2nd tier) | soccer | 3-way | 0 (0) | none | $919 (12) | 0.010 | 1/1 +0.03 | - | thin |
| utr | UTR Pro Tennis Tour | tennis | 2-way | 0 (0) | none | $8,699 (24) | 0.020 | 2/2 +0.04 | 1/1 | low-tier tennis |
| cs2 | Counter-Strike 2 | esports | 2-way | 1,873 (0) | no recorded end | $4,634 (39) | 0.030 | 2/2 +0.05 | 6/6 | - |
| idnsl | Indonesia Super League | soccer | 3-way | 2 (0) | thin | $8,916 (2) | - | 2/2 +0.05 | - | - |
| jpbl | B.League (Japan) | basketball | 2-way | 0 (0) | none | $22,848 (3) | - | 3/3 +0.07 | - | - |
| itfwo | ITF women (W15-W100) | tennis | 2-way | 343 (0) | no recorded end | $32,803 (24) | 0.020 | 6/6 +0.13 | 1/1 | low-tier tennis |
| itfme | ITF men (M15/M25) | tennis | 2-way | 205 (0) | no recorded end | $19,354 (19) | 0.030 | 9/9 +0.21 | 1/1 | low-tier tennis |
| btc | Bitcoin price contracts | crypto | price ladder | (non-sports) | - | $577 (50) | - | 20/20 +0.43 | 23/23 | - |
| cfb | College football | american football | 2-way | 299 (0) | some | $1,433,057 (5) | 0.007 | - | 4/4 | - |
| lpa | Liga Profesional (Argentina) | soccer | 3-way | 150 (62) | judgeable | $14,482 (9) | 0.010 | - | 3/3 | - |
| lmx | Liga MX | soccer | 3-way | 86 (27) | some | $67,845 (2) | - | - | 2/2 | - |
| nhl | NHL | ice hockey | 2-way | 77 (0) | some | $229,291 (2) | - | - | 2/2 | - |
| lexp | Liga de Expansion MX | soccer | 3-way | 0 (0) | none | $3,694 (4) | - | - | 4/4 | - |
| ebfcwc | eBattles e-soccer: Club World Cup | e-soccer | 3-way | 0 (0) | none | $22 (5) | - | - | 5/5 | made-for-betting, thin |
| setkamemd | Setka Cup Moldova, men | table tennis | 2-way | 0 (0) | none | $9,208 (23) | 0.020 | - | 1/1 | made-for-betting |
| lol, wnba, lco, pl1, lpc, uru1, t20iwcr | (one paper bet each, all won) | | | | | | | - | 1/1 | |

## Warning signs

### Thin markets (few traders, wide books)

The venue's own book stats give the dollars that changed hands over a market's life. Under **$1,000** (a plain cut:
a $1 ticket is then more than a thousandth of all trading, and one stale order sets the printed price):

- **e-soccer, all eBattles leagues: $22-54 per game market** (306 markets), the thinnest the desk trades.
- **DEL $48** (6), **KHL $77** (3), Czech Extraliga $511 (5), Swiss National League $928 (4), Finnish Liiga $943 (6):
  European hockey on this venue is barely traded. The NHL is the exception ($229,291, n = 2).
- **BSKT Cup 3x3 basketball: median $0**, at most $54 in any of 21 recorded markets, median spread 0.96.
- Darts: PDC $243 (8, spread 0.33), MODUS $339 (7).
- Some small soccer: UEFA women's WC qualifying $895 (42), Ykkosliiga $919 (12), Swiss Challenge League $899 (15),
  LOI First Division $999 (15); single-game readings (n = 3) for Eredivisie, Saudi Pro League, Serie B, Fortuna
  Liga, National League, Cyprus, RPL, Serie C.
- Bitcoin price contracts $577 (50): thin per contract, but the price comes from Bitcoin itself.

For scale: ATP $129,853, WTA $156,197, ITF $19,000-33,000, Setka Cup Ukraine $16,662, college football $1.4 million.
**Setka Cup is not thin** on this venue; its problem is the next section.

### Kinds of competition with an integrity risk (background, not from our data)

These are public facts about the *kind* of league, not something our 91 bets showed:

- **Made for betting**: Setka Cup (Ukraine, Czechia, Moldova; men and women) and Czech Liga Pro table tennis, matches
  around the clock; **eBattles e-soccer** (results "sourced from ESportsBattle", players playing EA FC games of a few
  minutes); BSKT Cup 3x3; MODUS Super Series darts. Real bets: 21, won 18, -$2.47.
- **Low-tier tennis**: ITF World Tennis Tour (M15/M25, W15-W100) and the UTR Pro Tour, where most tennis
  match-fixing sanctions fall. Real bets: 17, won 17, +$0.38.
- **Youth, amateur and low-tier football**: US college soccer (`ncaaws` 369 and `ncaams` 213 winner markets in the
  next 24 h, the largest single block on the venue tonight), Brazilian U20 / U23 and women's state leagues, Italian
  Serie C, Belgian and Swiss 3rd / 4th tiers, second divisions of Paraguay, Venezuela, Guatemala, Montenegro,
  Slovakia, Israel's Liga Alef. None of these has any history.

### 3-way games and impossible books

Every soccer and e-soccer game is three separate YES/NO markets. In an honest book the three YES prices add up to
about $1. The desk checks each leg alone, so a broken book can show two or three legs "near-certain" at once, and the
desk has no rule against buying more than one leg of a game. If it buys two legs at 0.97+, it pays at least $1.94
for at most $1.

| | games recorded | three YES bids add to > $1.02 | 2-3 legs near-certain at once (2026-10-09: in play only) | 2-3 legs passing the desk's buy test at once |
|---|---|---|---|---|
| e-soccer, 2026-10-09 15:54-22:51 UTC | 96 | 15 | 24 | 0 |
| real soccer, same window | 83 | 0 | 0 | 0 |
| e-soccer, listing at 2026-10-10 18:18 UTC | 22 | 6 | 5 | (not started) |
| college soccer, same listing (about 7 h before kick-off) | 194 | 3 | 0 | - |

And the real case, 2026-10-10 13:12 UTC: Sassuolo win, draw and Roma win all bought at 0.98 (bid 0.97, ask 0.98:
each leg passed the spread check), Sassuolo won, two legs lost: -$1.94 on one game.

Also in the rules text: a cancelled e-soccer game settles every leg at **$0.33**, a Setka / 3x3 walkover at **$0.50**;
a 0.98 buy then loses 48-65 cents even though "nobody lost".

## Which sports at which hours (UTC)

| hours (UTC) | what the venue offers (winner markets starting, next 24 h) | what the desk bought |
|---|---|---|
| 22-05 | Americas soccer (and US college soccer from 23:00), table tennis all night, tennis from 00:00 (Asia), NHL / college football into the night | **paper** (current rule): crypto 23, soccer 13, e-soccer 8, esports 7, tennis 7, table tennis 7, ... |
| 05-14 | tennis dominates (ITF / Challenger / WTA in Europe, 38-57 markets an hour 07-10), Setka table tennis, some esports | **real**: tennis 28, table tennis 17 (of them 16 Setka Ukraine), crypto, a few soccer / basketball, e-soccer at 10 and 13 |
| 11-18 | European soccer (48-192 markets an hour), basketball, European hockey | real, 2026-10-09 17:52 (adopted from the venue): DEL hockey 2, soccer 3, crypto 3 |
| 18-20 | e-soccer bursts (48 eBattles markets in the 18:00 hour today), soccer, college football | - |

## What this means (for the owner to decide; this map changes no code)

These only ever make the desk buy **less**:

1. **One outcome per game.** Never buy a second leg of a game the desk already holds (two legs of a 3-way game can
   never both win). This is arithmetic, not a fitted filter.
2. **Skip broken 3-way books**: if the three YES bids of a game add up to more than $1, treat the whole game as
   unreadable. Same reasoning.
3. **No real money where history is empty** (`history_level` "none" in the JSON: Setka Cup, all eBattles, DEL,
   Swiss, Finnish and Czech hockey, the AHL, most European basketball, darts, rugby, pickleball, US college
   soccer, youth and lower football). This is the lab's own rule ("no proof = no real money", PLAN Amendment 5); our
   7 losses are not the reason, and they are not evidence for it.
4. **Read the event's `live` flag**, not only its period word, so postponed or finished games never count as in play.
5. Which of the *judgeable* sports (ATP / WTA tennis, MLB, WNBA, MLS, Argentine, Brazilian, Chinese, Korean and
   Norwegian soccer) may keep real money is lab 4 P6's job, on history, by its pre-registered protocol.

## All league codes by sport and history level

Number in brackets = polymarket.com game-winner games with at least 50 fills.

- **soccer** (1,611 winner markets in the next 24 h). judgeable: mls (184), lpa (150), bra (107), csl (75), kl1
  (75), els (62); some: lco (92), lmx (86), lal (69), alsv (68), eflch (66), spl (55), ere (54), lal2 (54), ligpor
  (53), epl (50), sea (50), bun2 (47), sld (46), lg1 (44), pl1 (43), tsl (43), bun (36), pdc (33), slr (32), egpl
  (31); no recorded end: j1 (66); thin: bel1 (29), ecu1 (26), scp (26), swsl (25), ekst (21), vkl (21), lig2 (20), lpb
  (20), flc (18), srb (18), j2 (17), atbl (16), rpl (16), arg2 (14), uzb1 (10), swe2 (9), tff1 (9), hnl (7), irlp (7),
  brc (6), uru1 (6), grsl (5), nb1 (5), nor1 (4), pvl (4), btla (3), engnl (3), uslc (3), idnsl (2), lpc (2), nls (2),
  svnp (2), thai1 (2), lng (1); none: be1acff, be1vv, caru20, ch1cl, cyp1, den1, fnl, gaub, ghpl, gtasc, ilaln, irl1,
  isl1, lexp, minw, mne2, ncaams, ncaaws, ngnpfl, par1, par2, peu20, serca, sercb, sercc, svk2, swcl, uwwcq, ven2, ykk.
- **tennis** (436). judgeable: atp (3,641), wta (1,798); no recorded end: itfwo (343), itfme (205); none: atpdb,
  utr, wtadb.
- **table tennis** (155). thin: setkamecz (1); none: czechligapro, setkamemd, setkameua, setkawoua, wtt.
- **basketball** (103). judgeable: wnba (202); no recorded end: eurolg (31); thin: nbl (22), nba (17, preseason /
  summer only), acb (3), bbl (3), kbl (1), lba (1); none: aba, autbl, bskt3x3, bsl, cznbl, denbl, fra2, gbl, hunbl,
  ita2, jpbl, koris, lkl, lnb, slb, slnbl, svkbl, vtb.
- **american football** (103). some: cfb (299), nfl (111) (TRAIN is July to mid-August, before both seasons).
- **e-soccer** (66). none: ebfcwc, ebfpl, ebfsa, ebfwca, ebfwcb.
- **esports** (56). no recorded end: cs2 (1,873), lol (1,026), dota2 (427), valorant (396); thin: r6 (9); none: ow.
- **ice hockey** (54). some: nhl (77); thin: khl (1), shl (1); none: ahl, cehl, del, liiga, snhl.
- **baseball** (5). judgeable: mlb (1,182); no recorded end: kbo (85); thin: npb (17).
- **cricket** (10). some: t20icr (57); thin: odicr (29), t20iwcr (22), odiwcr (10), testcr (10).
- **mma** (12): ufc (203, no recorded end). **boxing** (7): thin (6). **darts** (14): modus, pdcdarts none.
  **rugby** (6): prem, top14, urc none. **pickleball** (8): ppa none.
- **non-sports**: `cpc-btc` (polymarket.com has 37,447 BTC markets) and `tc-temp` (2,205 city-temperature markets);
  judged by lab 4 P4, not by this map.

## How the numbers were made

- **Venue, now**: the public gateway `https://gateway.polymarket.us/v1/events?categories=sports` (no key), fetched
  2026-10-10 18:18 UTC twice: the desk's own query (start in the last 12 h to now + 5 min, 3 pages, 214 events) and
  the same widened to now + 24 h (16 pages, 1,534 events, 33,934 markets with the printed best bid / ask). Then
  `/markets/{slug}/book` for 1,177 markets (the desk's real and paper bets, the 834 sports markets of the 2026-10-09
  recorder snapshot, the 178 markets live now) for the lifetime trading stats, under two requests a second.
- **Venue, 2026-10-09**: lab 4's recorder (`lab4/us/`): one best bid / ask a minute for every recorded market,
  15:54-22:51 UTC, 768 sports settlements.
- **Desk**: `desk/history.json` (the desk's `/api/polydesk` export at 17:50 UTC): 91 settled real receipts; the paper
  rows still kept in its state (73 under the current rule, 44 older).
- **History**: lab 4's polymarket.com cache: 90,170 markets with at least $20,000 volume closed 2026-07-01 to
  2026-10-09, the P6 game facts (`p6_meta.parquet`: market type, start and finish) and the trade-tape sizes. A US
  league's history = the polymarket.com league code(s) of the same competition, checked by team names in the titles
  (all mappings and three example titles each are in the JSON). Game-winner = `sportsMarketType` "moneyline"; a game
  counts when its tape has at least 50 fills (lab 4's minimum); "recorded end" = the event's finish time lies between
  its start and the market's close (PLAN Amendment 5).
- Searched and not found anywhere in the history: Setka (except 2 Ukraine and 1 Czech markets), eBattles / e-soccer,
  DEL, Liiga, Czech Extraliga, Swiss hockey, AHL, UTR, darts (PDC, MODUS), Czech Liga Pro, 3x3, rugby union, pickleball,
  NCAA soccer, all doubles tennis.
- **Limits**: "$ traded" with n = 1-3 is one game. The 2026-10-09 recorder ran 7 hours on one day and only saw the
  150 newest live games at a time. The "would-have-bought on recorded quotes" readings in the JSON (68 buys, 65 won,
  -0.61 per $1 contract in total) are one evening of quotes, not history, and select nothing. Integrity flags are
  background about kinds of competition, not findings. The 18:18 UTC listing is one moment; e-soccer and Setka
  events are listed only a few hours ahead, so their 24-hour counts are low.
- Rebuild: `python research/lab4/US/venue_map_build.py` (reads the saved files; no network).
