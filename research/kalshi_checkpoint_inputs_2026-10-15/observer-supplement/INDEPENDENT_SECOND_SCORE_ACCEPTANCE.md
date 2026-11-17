# Second score retained: forecast miss

Verified unchanged source23e2 current observer's second forecast against the first original wrapper and a fresh official unauthenticated market GET. **It favored Down (Up probability21.383879%); the market finalized YES/Up.** This is a probability/direction miss, not a booked trading loss.

* `KXBTC15M-26OCT151830-30`: forecast payload22:20:00.065374UTC/publication22:20:00.071404112UTC, p=0.2138387913915002, q=0.21383879139150022, bin2 with prior n0/wins0.
* Score payload22:30:14.490194UTC/publication22:30:14.498982524UTC, outcome=true, exact frozen-forecast field match, recorded post_gaps empty. Official finalizedYES settlement22:30:01.881008UTC; opening strike82371.62; close22:30UTC. The rule compares final60-second BRTI average against opening60-second BRTI average using greater-or-equal.
* Second Brier baseline0.6180494459207772, shadow0.6180494459207772. First correct-direction score remains0.008383692762115782. Two-score mean **0.3132165693414465** for baseline and shadow, exactly matching original status. Expected bin2 update n1/wins1 follows code; production raw bins were not exported.
* Latest original22:36:39.285800367UTC: **3 forecasts,2 scored,2 unknown,1 pending**. Third forecast22:35:00.094867UTC/publication22:35:00.133843196UTC for1845ticker: p=0.46003552248597807, bin4/prior0. Its22:45 outcome is pending in this saved evidence. No outcome is inferred.

The first correct and second incorrect directions must both remain; n2 establishes neither accuracy improvement nor profitability. The failed predeclared21:45–22:00 capture stays failed, and old-source five-score archive stays separate. This supplement is observe-only, later opportunistic evidence. Empty recorded post_gaps is not continuous-feed certification.

Release must preserve the **actual latest** old-source dictionaries, counts and pending rows. This22:36 snapshot may change before the safe release minute; do not overwrite it with earlier0/1-score assumptions or omit the miss. Source candidate has not caused these observations. No strategy/cap/stop/resume/variable/money authorization follows.

Native public response/request metadata and exact selected original rows are saved alongside the detailed acceptance JSON. Eight originals in the2237wrapper; no duplicate Railway query, credential read or production mutation by reviewer.
