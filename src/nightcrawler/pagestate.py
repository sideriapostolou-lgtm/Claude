"""Data for the one page at ``/`` (owner: O6): ``/api/page``, built from the ledger ONLY (no network calls).

It combines what ``/api/state`` (:func:`nightcrawler.dashboard.build_state`) and ``/api/team``
(:func:`nightcrawler.teamroom.build_team_state`) already know, in plain words, plus the learning card and
the "ready for real money?" checklist (:mod:`nightcrawler.readiness`). Served by
:class:`nightcrawler.teamroom.TeamRoom` behind the dashboard token, scrubbed of secrets; every text taken
from the ledger is redacted, THEN clipped, and the page inserts it as text only.

Schema (lists capped: members 9, events <= 5, open trades <= 10, closed trades 10, variants 5)::

    {
      "version", "generated_at", "mode": "PAPER"|"LIVE", "refresh_s",
      "alerts": [{"level": "bad"|"warn", "text"}],                    # header banners, worst first
      "plain": {"about", "headline",                                  # the whole screen in plain words: see PLAIN
                "real": {"label": "Real money", "on": bool, "reported": bool, "paused": str|null,
                         "paused_kind": "risk"|"day"|"full"|"room"|null, "at_risk_usd": float|null,
                         "open_bets": int|null, "cash_usd": float|null, "result": str|null, "line",
                         "how": str|null, "limits": str|null, "verdict": str|null, "research": str|null,
                         "sports_line": str|null, "skips_line": str|null, "arbs_line": str|null},
                "pretend": {"label": "Practice (pretend money)", "line", "body"},
                "now": [str] (<= 3),
                "team": [{"id", "name", "job", "plain_role", "status_word": "working"|"waiting"|"idle"|"stuck",
                          "members": [member id], "latest": str|null, "latest_ts": float|null,
                          "latest_ago": str|null}],
                "said": {member id: {"ts", "text"}},                  # each member's newest event, plain words
                "jobs": {member id: str},                             # each member's own job (bubble labels)
                "glossary": [{"word", "means"}],
                "ticker": [{"ts", "who", "name", "text", "tone"}] (<= 8),   # the 3D world's ticker: TICKER
                "finished": [{"id", "ts", "who": "jet"|"voss", "what", "result": "won"|"lost"|"even",
                              "usd": float|null, "real": bool, "money": "real money"|"pretend"}] (<= 3),
                "goal": {"label", "strip_label", "strip_figure", "strip_figure_short", "strip", "aria", "today",
                         "strip_label_short", "line", "ember_line", "bill_line", "power_line", "plaque_line",
                         "floor_line", "lifeline_line", "reserve_line",
                         "reach_line", "streak_line", "day_lines" (<= 7), "best_line", "road_lines", "practice_line",
                         "crew_road_line", "honest", "postcard", "target_text", "bill_text",
                         "result": {"day", "title", "figure", "line", "streak"}|null,
                         "lines": {character: str|null}, "programmes": {"check_in", "tour": [{"who", "tag", "text"}]}
                         }|null},                                      # the town's goal in words: GOAL
      "money": {"label", "usd", "start_usd", "sol", "sol_usd", "withdrawn_sol",  # live: sent back to the owner
                "since_start": {"usd", "pct"}, "today": {"usd", "pct"},   # the bot's own result (in SOL,
                "sol_price_effect_usd",                                   #  shown at today's SOL price)
                "curve": [[ts, usd], ...], "chart_ready": bool,           # chart after one hour of data
                "as_of": ts|null,                                         # the last money check
                "polymarket": {"mode": "paper"|"live", "label", "as_of": ts|null,   # see POLYMARKET; null: desk off
                               "status": str|null,                        # the desk's own word on live (why not)
                               "paper": {"label": "Paper money (pretend)", "open", "today_usd", "since_start_usd",
                                         "settled_today", "won_today", "settled_total", "won_total"},
                               "real": {"label": "Real money", (the same keys), "at_risk_usd", "contracts",
                                        "cost_usd", "value_usd", "venue_at", "cash_usd", "cash_at",
                                        "pending", "pending_usd",          # orders the venue has not confirmed
                                        "stop_room_usd": float|null,       # room left under the loss stops
                                        "stop_room_limit": "day"|"total"|null}|null,
                               "real_closed": [{"question", "settled_at", "pnl_usd", "won"}] (<= 5),  # newest first
                               "guard": {"verdict", "reason", "paused", "since", "line", "on", "candidate",
                                         "real": {"verdict", "reason", "paused", "since", "line"}|null}|null,
                               "settled_real": [{"ts", "text"}] (<= 3),   # its newest REAL settlements
                               "skips": {"counts": {reason: n}, "sports": {sport: n}},   # today (UTC): SKIPS
                               "sports": [{"sport", "real": "allowed"|"blocked", "history", "why",
                                           "paper": {"settled", "won", "pnl_usd", "verdict", "phrase"}|null,
                                           "flagged": bool}],
                               "real_sports_allowed": [sport],
                               "arbs": {"today_seen", "today_bought", "today_checked", "today_still_there",  # ARBS
                                        "sets_paper", "open_sets", "settled_sets", "pnl_usd", "broken",
                                        "last": [{"name", "total", "edge", "min_size": float|null,
                                                  "still_there": bool|null}] (<= 5)}}|null,
                "trend": {"mode": "paper", "label": "Paper money (pretend)", "as_of": ts|null,   # see TREND; null: off
                          "sleeve_usd", "equity_usd", "today_usd", "since_start_usd", "hold_since_start_usd",
                          "in_market": {"BTC": bool, "ETH": bool, "SOL": bool}, "started": "YYYY-MM-DD"|null,
                          "problem": str|null, "lab": {"since_start_usd", "hold_since_start_usd"}|null,
                          "reset_from": str|null}|null},
      "town": {"label", "cost_per_day_usd", "cost_today_usd", "cost_since_start_usd": float|null,  # see TOWN
               "income_today_usd": float|null, "income_since_start_usd": float|null,
               "covered_today": bool|null, "covered_since_start": bool|null, "line",
               "polymarket": {"paper": {"label", "open", "today_usd", "since_start_usd", "line"},  # the desk in words
                              "real": {"label", "open", "contracts", "cost_usd", "value_usd", "today_usd",
                                       "settled_today", "won_today", "since_start_usd", "cash_usd", "line"}|null}|null,
               "trend": {"line"}|null,                                    # the trend desk in words (TREND)
               "goal": {"label", "target_usd", "target_ok", "is_cost": false, "counts": "real money only", "day",
                        "day_start", "day_end", "day_n", "real_on", "real_today_usd", "parts", "peak_today_usd",
                        "bill_per_day_usd", "bill_covered_by_real", "bill_share_real", "power", "rungs", "progress",
                        "tier", "next", "beyond_usd", "floor", "lifeline", "reserve", "reach", "mood", "stand_down",
                        "days", "streaks", "best_day", "road", "practice"}|null},   # the town's goal: GOAL
      "team": {"counts": {status: n}, "members": [{"id", "name", "role", "status", "why", "doing",
                                                    "last_activity", "events", "bars"?,
                                                    "risk_wall"?: {...}}]},   # the risk member only: RISK WALL
                                                    # status "absent": the Coach is not built (not counted)
      "trades": {"open": [{"coin", "entry_usd", "now_usd", "pnl_usd", "pnl_pct", "opened_at", "partial", "foreign"}],
                 "closed": [{"coin", "opened_at", "closed_at", "pnl_usd", "pnl_pct", "result", "why"}],
                 "summary": {"label", "won", "lost", "even", "total", "since": ts|null, "order": "WLE…", "result",
                             "real": {"label", "won", "lost", "settled", "since", "order", "lines", "result"}|null},
                 "max_open"},
      "recap": {"date", "tz", "window", "events", "events_total", "quiet", "closed", "real", "pretend"},  # RECAP
      "research": {"labs": [{"lab", "question", "verdict", "date", "reading", "plain", "trials"}],  # see RESEARCH
                   "trials_total", "as_of", "rule"},
      "learning": {"source": "card"|"missing"|"error", "state", "headline", "variants": [{"name", "n", "avg",
                   "proof"}], "data", "rule": str|null},
      "experience": {...},                                            # the report cards: see EXPERIENCE below
      "ready": readiness.readiness(...),
      "wallet": {"address", "sol", "checked_at", "own", "help", "paper_note", "note",   # the deposit address
                 "keep_note", "last_withdrawal": {"sol", "to", "at", "signature"}|null},
      "withdraw": {"status", "to", "level", "text"}|null,     # WITHDRAW_TO, or the hold after it (also a banner)
      "receipts": {"count", "verified", "first_bad_seq", "head", "head_short"},
      "usage": [{"label", "pct": float|null, "level": "ok"|"warn"|"over"|null, "text", "measured": bool}],
      "about": {"version", "uptime_s", "commit", "started_at"}
    }

MONEY honesty (same rule as the old dashboard tiles): "since start" and "today" are the bot's result
measured in SOL - the unit the risk limits use - and shown in dollars at today's SOL price, so a SOL price
rise can never paint a losing bot green. The SOL price effect is reported apart.

TOWN ("keep the town alive", :func:`town_ledger`): the desks must earn more than the town costs to run. Costs:
Railway's price per month (``TOWN_RAILWAY_USD_MONTH``; a day is 1/30 of it) plus the AI judge's spending
(``judge.cost_usd_today`` and ``judge.cost_usd_total`` of ``/api/state``; a missing figure counts as nothing
recorded, and without a figure for today the total is spread over the days run so far). ``cost_per_day_usd``: the
day rate, Railway's day plus the judge's spend today. ``cost_today_usd``: the cost so far today, Railway's day
prorated over the part of the UTC day that has passed (since the start, when the run began today) plus the
judge's spend today. ``cost_since_start_usd``: Railway's price over the run so far plus the judge's total. The run
starts at the ledger's first record (the first boot on this volume) or at ``engine.started_at``, whichever is
earlier: a redeploy restarts the engine, not the bill, the judge's total or the money since start. Income is the
money card's own result (``money.today.usd``, ``money.since_start.usd``): the SOL bot's figures, nothing else.
Whatever is not known is null (income before the first money check; the since-start cost before the first record)
and the line says so; ``covered_*`` is null while either side is unknown. The Polymarket desk is counted apart
(``town.polymarket``, POLYMARKET below): one line for its paper book and, only while it has a real book, one for its
real money, and ``line`` names each desk ("the Solana desk lost $3.18 and the Polymarket desk lost $1,345.53 today
(paper money, pretend)"); no figure of one kind of money is ever added to another. Only real money can cover the bill;
practice never counts (``covered_*`` compare the money card's own figures and stay as they were for the 2D page, which
says "covered" only while that card is real money; ``goal.bill_covered_by_real`` is the real one: GOAL below).

GOAL (:func:`town_goal_block`, :mod:`nightcrawler.towngoal`): DISPLAY ONLY, the 3D world's goal tower. ``town.goal`` is
the owner's goal for the team, ``TOWN_GOAL_USD`` real dollars a day (read leniently: ``target_ok`` is false and 100 is
shown when the setting cannot be read), never a cost (``is_cost`` is always false; the town's running cost stays
``cost_per_day_usd`` above, a whole day's bill). Only REAL money counts toward it: ``parts`` are the Polymarket desk's
real book (``money.polymarket.real``) and the Solana bot's own only while it runs live, ``real_today_usd`` their sum to
the cent (null without a real book, never a zero). The rungs (above zero, covers the bill, 1 % and 10 % of the goal, the
goal, 1.5x, 2x, 3x) light by the cent; ``reached`` also marks a rung today's real settlement receipts touched earlier in
the day (``peak_today_usd``, null unless they add up to today's figure); ``power`` is ``own`` once real money covers the
bill, else ``backup`` (the owner pays), null when not known (``bill_covered_by_real`` and ``bill_share_real`` too, until
real money has reported today). ``floor`` and ``lifeline`` are the real desk's day and total loss stops
(``risk_wall.real_caps``), ``reserve`` the venue's cash (deposits plus results: shown, never counted), ``reach`` the
most today's settled bets could have made by the rule's own price (an upper bound) and the least a loss costs
(``loss_min_per_bet_usd``: the rule buys at its price or above). ``mood`` (stopped_for_good, unknown, off, stand_down,
waiting, goal, own_power, climb) picks the words. ``day`` is the desk's own UTC day; ``days``, ``streaks`` and
``best_day`` come from its day book (``live_days`` in its state file, read only) and are null unless that book agrees
with the money card to the cent. ``practice`` is the pretend books apart (``counts_toward_goal`` always false) and the
Solana bot's road to real money (the checklist's labels only, never a reason, and never its security steps: ``done`` and
``total`` still count them). ``plain.goal`` says it all in fixed templates (the one token the page fills is
``{local_reset}``, the day's end on the viewer's clock), with each character's line and the world's two programmes
(``check_in``, ``tour``). A failure gives null for both (``town_goal_failed`` in the logs), never a made-up zero;
nothing here reaches a desk.

POLYMARKET (:func:`polymarket_desk`): the Polymarket desk's books (:func:`nightcrawler.polydesk.panel_state`, its
state file only), kept apart from the SOL wallet and from each other. ``paper`` is the desk's own paper tally (the
candidate rule's pretend tickets); ``real`` is what came from the venue's own book: the open positions the venue
holds (``live``), the desk's real settlements, the venue's contract count, cost and value (``exchange``) and its
cash (``balance``). ``real`` is null unless the desk has a real book (an open real position, a real settlement or
a contract at the venue) or the venue's cash was read; ``money.polymarket`` is null when the desk is off
(``POLYDESK_ENABLED``) or its state cannot be read: nothing is shown rather than a made-up zero. A paper tally of
zero before the desk's first round is marked ``as_of: null`` ("no round finished yet"). ``guard`` is the desk's
risk manager (:mod:`nightcrawler.deskguard` on the current rule's own record): the verdict (learning, losing,
winning, unclear), its reason with the numbers, whether new buys are paused and since when (UTC), and the page's
``line``; while it is paused the town's paper line and its sentence say "paused by the risk manager" (the real
line, and a sentence of its own, when only the real buys are paused). ``candidate`` is true only for a rule that
passed lab 4 (none has: a winning paper record is never called a candidate for real money). ``status`` is the
desk's own sentence on live mode (``live_status``: why it stays on paper although live was asked for, e.g. a rejected
key or the total-loss cap; or the day's loss cap), null when it has none. ``real.pending`` / ``pending_usd`` are the
real orders the venue has not confirmed yet (open real money until its book says), ``stop_room_usd`` what the loss
stops still let out if every open bet and unconfirmed order lost (``stop_room_limit``: the stop that binds).
SKIPS: ``skips`` counts today's picks the rule did not buy, or did not buy with real money, by reason (``sports_no_real``
a game practised instead of a real bet, ``incoherent_game`` a game whose prices did not add up, ``incoherent_question``
the same for a non-sports question's answers (a price range's buckets), ``never_traded`` a
market not yet traded near the price, and the desk's other reasons), each market or game once a UTC day;
``sports`` is each sport with its real-money state (no sport is allowed: lab 4's history test passed none), the
history's verdict and reason (:data:`nightcrawler.polydesk.SPORT_HISTORY`) and its practice record.
ARBS: ``arbs`` is the desk's no-lose check (``polydesk.arbs_view``, PRACTICE only, never real money): today's (UTC)
questions whose every answer cost under $1 together, fees included (``today_seen``), how many it bought on paper,
checked again a round later and found still buyable, the paper sets' all-time tally (bought, open, settled, P&L in
pretend dollars, ``broken``: sets that paid back less than they cost) and the newest five; each number type-checked.

TREND (:func:`trend_desk`): the trend desk's paper book (:func:`nightcrawler.trenddesk.panel_state`, its state file
only), a forward test of lab 3's 50-day trend rule on BTC, ETH and SOL with a pretend sleeve. PAPER ONLY: the desk
has no real-money path at all. ``as_of`` is the last daily close it booked (null before the first one: the figures
are then the untouched sleeve). ``equity_usd``, ``today_usd`` (the last day's change) and ``since_start_usd`` are the
rule's book kept as a real account would keep it: three separate thirds, one per coin, never re-balanced.
``hold_since_start_usd`` is the benchmark the rule has to beat: holding the three, bought on day one and never
touched (the desk's ``bh`` book, same costs). ``lab`` is lab 3's own reckoning of both (the book put back to thirds
every day for free), for comparison with the lab only, never the result. ``problem`` says in plain words when the
book is behind (Coinbase not read, a candle late); ``reset_from`` names the earlier record this one replaced because
it could not be read (null otherwise). ``town.trend.line`` says the same in one sentence ("Trend desk (paper,
pretend): in BTC and SOL, out of ETH; since start +$1.20 vs holding the three (bought on day one, never touched)
+$0.40"; "record restarted <day>" after the label while ``reset_from`` is set). Its figures are never added to the
SOL wallet's, the Polymarket desk's or the town's income: the town's own line and bars are untouched. Null when the
desk is off (``TRENDDESK_ENABLED``) or its state cannot be read.

TROPHIES (``trades.summary``, the 3D world's trophy shelf): ``closed`` is capped at 10, so the summary counts EVERY
closed trade of the Solana bot in this mode (``won``: a positive result in SOL, ``lost``: a negative one, ``even``,
``total``; ``label`` the money card's label: pretend unless the bot itself runs live), ``since`` is the first closing
time (null without one) and ``order`` the results newest first, one letter each (``W``/``L``/``E``), the last
:data:`SHELF_MAX` of them. ``real`` is the Polymarket desk's real money only (null unless the desk has a real book):
the desk's own totals from ``money.polymarket.real`` (``won`` of ``settled``, ``lost`` the rest), ``order`` its real
settlements newest first from the receipts (a positive result is ``W``), ``since`` the first one's time and ``lines``
the newest real settlements in the desk's own words (``money.polymarket.real_closed``), each "REAL". ``result`` is
the money each tier stands for, in the plain words' wording: the Solana bot's since start (the money card's, real
money only while it trades real money) and the desk's real result since start (``money.polymarket.real``), so a row
of trophies never reads as a profit the money does not show (a near-certain rule wins cents and loses dollars). The
shelf draws one trophy per win and one tile per loss and says how many more are not on it; nothing else of a trade
is in it.

RISK WALL (``team.members[risk].risk_wall``, the 3D world's gauge board): the risk panel's own numbers
(:mod:`nightcrawler.teamroom`: the share of today's loss allowance used, the trade slots in use, the daily stop, what
stops new buys, each desk's verdict and pause) plus ``real_caps``: the Polymarket desk's real money against its hard
limits, from ``money.polymarket.real`` and the settings (``open_usd`` of ``open_max_usd`` in open bets, ``day_loss_usd``
of ``day_max_usd`` lost today (UTC), ``total_loss_usd`` of ``total_max_usd`` lost in total; ``on``: the desk bets real
money now), null unless the desk has a real book.

RECAP (:mod:`nightcrawler.recap`): yesterday, the previous calendar day of the owner's time zone (``OWNER_TZ``), from
the ledger and its receipts only: at most 8 events in the page's plain words, each named for the member who made it
and marked ``real`` when it is real money, the Solana bot's trades closed that day (in dollars at this page's SOL
price, the same figure as ``trades.closed``), the real money's result since start when the day began and when it
ended (the desk's real book only), the practice line and ``quiet`` (the ledger holds nothing at all for the day).
The day's records are kept for :data:`nightcrawler.recap.RECAP_TTL_S` per day, zone and mode in ``memory`` (yesterday
does not change) and worded on every page; a failure to read them gives an empty recap, never a broken page.

RESEARCH (:func:`nightcrawler.research_board.research_state`): what the labs found, one row per lab, a FIXED copy of
the verdicts recorded in ``research/`` (not shipped in the image), each also in plain words (``plain``); a test keeps
the copy equal to the record.

PLAIN (:func:`plain_words`): the screen in plain words for a newcomer (both pages put it on top), built from this
page's own data only: every sentence is a FIXED template filled with the data's numbers and words, never an invented
fact. ``about`` says what the app is (:data:`PLAIN_ABOUT`). ``real`` is real money, called "real money" only where the
data says so (the Polymarket desk's ``mode: live``; the Solana bot only when the bot itself runs live): ``on``, the
line (the venue's cash, the money in open real bets and the real result since start with the finished bets won; "up
$X since start (real money)" is the only way a gain is ever worded), ``result`` (that result alone, once a real bet
has finished; the Solana bot's while it runs live), ``how`` (how the rule bets, from its settings: the price it buys
at, what a win and a loss are worth), ``paused`` (why no new real bet goes out now: the risk manager's pause, since
when; the day's loss limit reached; the open-money limit full, which is waiting, not a pause; the room left under a
loss stop smaller than one bet if every open bet lost, which is waiting too; ``paused_kind`` says which: ``risk``,
``day``, ``full`` or ``room``; else null), ``sports_line`` (why real money skips sports, from the history verdicts
:data:`nightcrawler.polydesk.SPORT_HISTORY` only, naming any sport ever allowed) and ``skips_line`` (what the desk
skipped today and why, from its own counts, the parts that are not zero), the desk's hard limits from its settings
and ``arbs_line`` (the no-lose check, "No-lose check (practice): ...", only on a day it found one; null
otherwise), the desk's hard limits from its settings and the lab's verdict on its
rule (:data:`nightcrawler.polydesk.RULE_LAB_PASSED`: no edge, so tiny amounts only; while it bets no real money, a
verdict that says so instead), plus the research line while no strategy has passed its locked test. Off, the line
says so with the desk's own reason (``status``) when the owner asked for live, and what is still at the venue; the
headline then says real money is off only when no real bet is still open. ``reported`` is false only while the owner
asked for live (``POLYDESK_MODE=live``) and the desk has not said anything yet (no state, no reason, no round): the
page then says it cannot tell instead of "pretend". ``pretend`` names each practice book apart, always "pretend": the
Solana bot (since start), the Polymarket desk's paper bets (since start, today's change beside it) and the trend desk
(since start, or when it starts); ``body`` is the same sentence without its label. ``now``: up to
:data:`PLAIN_NOW_MAX` of the team's freshest events (the last :data:`PLAIN_NOW_WINDOW_S`, the receipts' own log left
out), each "Name: what happened · how long ago", the common kinds put in plain words by fixed templates
(:func:`plain_event`), any other one as the bot wrote it ("paper" said "pretend"). ``team``: the six characters of the
3D world (:data:`nightcrawler.office3d.CAST3D`, the members each one plays) with a fixed one-line job
(:data:`PLAIN_JOBS`, saying which money each one handles, real only where the data says live), the worst status of
their members in one word ("stuck" for blocked) and their latest event; ``said`` is each member's newest event in the
same plain words (the 3D world's speech bubbles say it) and ``jobs`` each member's own job
(:data:`PLAIN_MEMBER_JOBS`: a bubble's label). ``glossary``: the words still on screen, each with one line. Real and
pretend figures are never added together, nor anything else.

TICKER and FINISHED (:func:`plain_ticker`, :func:`plain_finished`: the 3D world's ticker and replay banner, nothing new
in them). ``ticker``: the team's last :data:`PLAIN_TICKER_MAX` events of the last :data:`PLAIN_TICKER_WINDOW_S`, newest
first, each in the same plain words as ``now`` (:func:`plain_event`), with the character who made it (``who``, its
``name``) and the event's own tone; the receipts' own log is left out (it records every step) and the same words come
once. ``finished``: the newest :data:`PLAIN_FINISHED_MAX` things that really finished, newest first: the Solana bot's
closed trades (``trades.closed``: the coin, its result and the dollars of its ``pnl_usd``, real money only while the
bot itself runs live) and the Polymarket desk's settled REAL-money bets (its own events "Settled: … (real)", read from
the desk's whole event log, ``money.polymarket.settled_real``, never the team row's last five: one round can settle
several bets and add a pause and a lesson; the question, won or lost and the dollars, only while the desk is on). A
practice bet that settles is not in it. ``usd`` is the amount without its sign (the result says which way), null when
unknown; ``money`` is "real money" or "pretend"; ``id`` stays the same from poll to poll, so a page replays each one
once.

LEARNING: :func:`learning_card` calls ``nightcrawler.learn.card.learning_card_state(settings, now)`` when
that module exists (it is built on another branch) and keeps only these keys, each type-checked::

    headline: str, state: str, variants | top_variants: [{name | id, n | trades | n_trades,
    avg | average (PERCENT per trade), proof | proof_progress (0..1)}], data | data_line: str,
    champion: str | {"name": str}, champion_passed_locked_test: bool, paper_matches_backtest: bool,
    paper_matches_backtest_reason | paper_reason: str, updated_at: epoch seconds (not in the future),
    can_stop_trading: bool (the module really can turn real trading off on its own)

Three honest outcomes: ``source: "card"`` (a card with a headline or a state), ``"missing"`` (the module is
not installed: the Coach shows "not built yet" and is left out of the team counts) and ``"error"`` (the
module raised or returned something that is not a card: the Coach is Blocked and checklist steps 1-2 say
unknown). Only an explicit ``True`` ever counts towards the checklist, and the "can turn real trading OFF"
rule is shown only when the card says ``can_stop_trading: true``. Wrong-typed values are dropped.

EXPERIENCE (docs/EXPERIENCE.md §9): :func:`experience_card` calls
``nightcrawler.experience.state.experience_state(settings, now)`` when that module exists (another team builds
it) and keeps exactly the keys of the §9 schema, each type-checked; every key is always present and unknown
values are null::

    {"source": "state"|"missing"|"error", "headline": [str, str], "bars_line", "money_line", "caveat",
     "team": {"graded", "days", "practised", "practised_window", "skills_shown", "skills_measurable": 4,
              "collecting", "not_measured": [str], "updated_at"},
     "members": {member id: {"kind", "label", "chip", "line", "graded", "days", "practised",
                             "metrics": [{"name", "value", "lo", "hi", "baseline", "unit", "text"}] (<= 3),
                             "exam": {"split", "version12", "date", "result", "current"}|null,
                             "trend": [[week_start, value, lo, hi]] (<= 8), "version_line", "independent",
                             "lessons": {"open", "testing", "adopted", "rejected"}, "coverage", "budget_left"}},
     "loss_types_week": [{"type", "n", "expected", "text"}] (<= 3), "lessons": [{"id", "status", "text"}] (<= 3),
     "playbook": {"validated", "rejected", "in_bot_contradicted", "in_bot_unsupported", "testing",
                  "false_keep_bound"}}

The honesty rules of §5.1 and §8.4 are checked HERE too, at the page's boundary, and a state that breaks one is
shown as ``source: "error"`` (nothing of it is shown): each member has the card kind of :data:`EXPERIENCE_KINDS`
and a label of that kind; "Skill shown" and "Worse than chance" need a primary band entirely on one side of the
chance baseline; "Meets the bar" needs a band on the good side of the bar; the Broker is never graded on paper;
the skill count equals the members labelled skilled. The chip WORD always comes from the label
(:data:`EXPERIENCE_CHIPS`), never from the state's own text. The money line says
:data:`EXPERIENCE_MONEY_LINE` unless the Coach's own card is ``paper_champion``, ``live_ready`` or ``live``, and
the caveat is fixed. Report cards never feed the checklist or the banners: they cannot turn trading on. The
playbook counts fall back to the static ``experience/playbook.json`` (generated from GROUNDED) when the state
has none; an unreadable file gives null counts, never zeros.

READY: the checklist (:mod:`nightcrawler.readiness`) never says Ready while any engine banner is up, and
reads the bot wallet's SOL from the last live equity snapshot (live) or the engine's paper-mode reading
(:mod:`nightcrawler.botwallet`), trusting a reading of the last :data:`WALLET_MAX_AGE_S` only.

WALLET: the bot wallet's PUBLIC address (live: kv ``wallet.pubkey``; paper: the bot's own wallet, kv
``keystore.pubkey``, or the address the engine read) with the same SOL reading, and how to fund it from
Phantom (live: right after a withdrawal landed, the balance the withdrawal read, until an equity snapshot is
newer). WITHDRAW: :func:`nightcrawler.withdraw.page_view` of kv ``withdraw.state`` while WITHDRAW_TO is set (or
of the hold after a live withdrawal), also the first banner (red while it is under way; it replaces the
kill-switch banner the engine's forced sell-off or hold would show). The money card adds back only SOL sent
back that the latest equity point already reflects. A wallet the bot made itself but does not use
(``BOT_WALLET_MODE=env``) is a banner too.
"""

from __future__ import annotations

import functools
import itertools
import json
import math
import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from nightcrawler import __version__, towngoal, trenddesk
from nightcrawler.botwallet import saved_balance, wallet_configured
from nightcrawler.broker.keystore import KV_GENERATED, unused_wallet
from nightcrawler.clock import utc_day
from nightcrawler.config import Settings
from nightcrawler.dashboard import build_state, scrub
from nightcrawler.deskguard import VERDICTS as GUARD_VERDICTS
from nightcrawler.ledger import LedgerError
from nightcrawler.logging_setup import get_logger, redact_text
from nightcrawler.models import LAMPORTS_PER_SOL, EquityPoint
from nightcrawler.office3d import CAST3D
from nightcrawler.page import LEARNING_RULE, MEMBERS, REFRESH_S
from nightcrawler.polydesk import (
    ARB_SHOWN,
    REAL_SPORTS_ALLOWED,
    RULE_LAB_PASSED,
    SKIP_REASONS,
    SPORT_HISTORY,
    SPORT_HISTORY_POOLED,
    load_state,
    panel_state,
    state_path,
)
from nightcrawler.readiness import CHECK_LABELS, readiness
from nightcrawler.recap import RECAP_TTL_S, collect_recap, day_window, empty_recap, render_recap
from nightcrawler.research_board import research_state
from nightcrawler.teamroom import ENGINE_STALE_S, FUTURE_SKEW_S, build_team_state, derive_status, duration_text
from nightcrawler.withdraw import fresh_balance, last_withdrawal, live_hold, page_view, saved_state, withdrawn_lamports

__all__ = ["EXPERIENCE_CAVEAT", "EXPERIENCE_CHIPS", "EXPERIENCE_KINDS", "EXPERIENCE_MONEY_LINE", "GLOSSARY",
           "LEARNING_RULE", "MEMBERS", "PAPER_LABEL", "PLAIN_ABOUT", "PLAIN_FINISHED_MAX", "PLAIN_JOBS",
           "PLAIN_MEMBER_JOBS", "PLAIN_TICKER_MAX", "PLAIN_TICKER_WINDOW_S", "PLAYBOOK_PATH", "PRETEND_LABEL",
           "REAL_LABEL", "SHELF_MAX", "STALE_BANNER_S", "TOWN_MONTH_DAYS", "WALLET_MAX_AGE_S", "build_page_state",
           "experience_card", "goal_books", "goal_inputs", "learning_card", "plain_event", "plain_finished",
           "plain_ticker", "plain_words", "polymarket_desk", "real_caps", "recap_state", "town_goal_block",
           "town_ledger", "trend_desk"]

log = get_logger(__name__)

#: The header turns red when the engine's heartbeat is older than this (it beats every 15 s); the team
#: room blocks every member from the same moment, so the banner and the chips always agree.
STALE_BANNER_S = ENGINE_STALE_S
#: The checklist trusts a bot wallet balance read this recently only (live: every minute; paper: 10 min).
WALLET_MAX_AGE_S = 3600.0
#: The learning module itself, as Python names it when it is absent.
_LEARN_MODULES = ("nightcrawler.learn", "nightcrawler.learn.card")
CHART_MIN_SPAN_S = 3600.0
OPEN_MAX = 10
CLOSED_MAX = 10
#: The 3D world's trophy shelf: one letter per closed trade (or real bet) in ``trades.summary``, newest first.
SHELF_MAX = 200
COIN_MAX = 24
WHY_MAX = 60
TEXT_MAX = 160
VARIANTS_MAX = 5
#: How to fund the bot wallet, for an owner with only the Phantom app.
FUND_HELP = "To fund: in Phantom tap Send, choose SOL, paste this address."
#: The bot's own wallet: its key exists only on the volume (broker/keystore.py).
KEEP_NOTE = ("Its key exists only on the Railway volume: keep the volume's backups on, and never delete the volume "
             "or the service while it holds SOL (withdraw first).")
#: The learning card is recomputed at most this often (the page refreshes every few seconds).
LEARNING_TTL_S = 60.0
#: The Coach counts as working when its card was updated this recently (it learns nightly).
COACH_WINDOW_S = 26 * 3600.0
DAY_S = 86_400.0
#: The town's hosting bill is a monthly price: a day of it is 1/30.
TOWN_MONTH_DAYS = 30.0
#: The money labels: the page must always make clear when the money is pretend.
PAPER_LABEL = "Paper money (pretend)"
REAL_LABEL = "Real money"
#: The practice books' label in plain words (``plain.pretend``).
PRETEND_LABEL = "Practice (pretend money)"
#: The page's own minus sign (U+2212), as its script prints a signed dollar figure.
_MINUS = "−"

#: PLAIN: what the app is, in one sentence (``plain.about``): the first line of the plain words on both pages.
PLAIN_ABOUT = ("Nightcrawler is a bot: a computer program that finds trades and bets and places them by itself, day "
               "and night.")
#: PLAIN: each character's job in one line (``plain.team``), keyed and named like
#: :data:`nightcrawler.office3d.CAST3D`, in the order the pages list them (where a coin's trip starts first).
#: ``{desk}`` is the Polymarket desk's money and ``{solana}`` the Solana bot's, each "real money" only while the data
#: says that one is live, else "pretend money" (:func:`_plain_team`); the receipts are no money at all.
PLAIN_JOBS: dict[str, str] = {
    "pip": "finds new crypto coins for the Solana bot ({solana})",
    "nyx": "checks each coin for scams and waits for the buy signal ({solana})",
    "rook": "keeps each coin trade small and stops losses ({solana})",
    "jet": "places the Solana bot's trades ({solana})",
    "mote": "keeps the tamper-proof records",
    "voss": "bets on yes/no questions at Polymarket ({desk}) and asks the AI judge about coins",
}
#: PLAIN: each bot member's own job in a few words (``plain.jobs``: the 3D world's speech-bubble labels), so an event
#: is labelled with the part of the bot that made it, never with another part its character also plays.
PLAIN_MEMBER_JOBS: dict[str, str] = {
    "crawler": "finds new coins", "cocoon": "checks each coin for scams", "strategy": "waits for the buy signal",
    "radar": "checks for danger right before a buy", "judge": "asks the AI judge about each coin",
    "broker": "places the Solana bot's trades", "risk": "keeps each trade small and stops losses",
    "receipts": "keeps the tamper-proof records", "coach": "learns from the bot's past trades",
    "predict": "bets on yes/no questions at Polymarket",
}
#: A member's status chip in one plain word (the worst of a character's members wins, in this order).
PLAIN_STATUS = {"blocked": "stuck", "working": "working", "waiting": "waiting", "idle": "idle"}
PLAIN_NOW_MAX = 3
#: "Right now" is the last six hours: an older event is not happening now (its age is said either way).
PLAIN_NOW_WINDOW_S = 6 * 3600.0
PLAIN_EVENT_MAX = 110  # one event's words, before "· N min ago"
#: The 3D world's ticker (``plain.ticker``): the team's last this many events, from the last day only (each one says
#: the time it happened, and an older one would read as today's).
PLAIN_TICKER_MAX = 8
PLAIN_TICKER_WINDOW_S = 24 * 3600.0
#: The newest finished trades and real-money bets the 3D world may replay (``plain.finished``).
PLAIN_FINISHED_MAX = 3
#: The Polymarket desk's own event for a settled REAL-money bet (polydesk: "Settled: <question> · won +0.03 $ (real)").
_REAL_SETTLED = re.compile(r"Settled: (?P<q>.+) · (?P<res>won|lost) (?P<pnl>[+-]?\d+(?:\.\d+)?) \$ \(real\)")
#: The headline: at most this many characters (two lines on a 390 px phone).
PLAIN_HEADLINE_MAX = 90
#: The real-money bets count as small (the headline's "Voss's small Polymarket bets") while their open-money cap is
#: at most this.
PLAIN_SMALL_DESK_USD = 50.0
#: The lab's verdict on the Polymarket desk's rule (polydesk.RULE_LAB_PASSED), shown wherever its real money is: while
#: it bets real money, and apart while it does not (it then never says the rule trades real amounts).
VERDICT_NO_EDGE = ("This rule did not pass our tests for a real edge (proof that it wins over many bets), so it trades "
                   "only tiny real amounts with hard limits.")
VERDICT_NO_EDGE_OFF = ("This rule did not pass our tests for a real edge (proof that it wins over many bets); it "
                       "places no new real-money bets now.")
VERDICT_PASSED = "This rule passed our lab's locked test; it still trades only small real amounts with hard limits."
VERDICT_PASSED_OFF = "This rule passed our lab's locked test; it places no new real-money bets now."
#: The research record so far, shown while neither the desk's rule nor the Coach's champion has passed its locked test.
RESEARCH_LINE = "No strategy tested so far has passed our lab's test for a real edge."
#: The words still on screen somewhere, each in one line (``plain.glossary``). Fixed text: no figure in here.
GLOSSARY: tuple[tuple[str, str], ...] = (
    ("Real money", "Actual dollars at stake. The pages call money real only where the bot's own data says so."),
    ("Pretend money (paper)", "Practice: trades made on paper with made-up money, so nothing is won or lost for real."),
    ("Prediction market", "A market where people buy yes or no on a question about the future; Polymarket is one."),
    ("Polymarket", "A US exchange for yes/no questions about the future; each correct contract pays $1."),
    ("Contract", "One Polymarket share: it pays $1 if its answer comes true and nothing if not."),
    ("A real edge", "Proof, from tests on past data, that a way of betting wins more than it loses over many bets."),
    ("The desk", "The Polymarket desk: the part of the bot that bets on Polymarket's questions (Voss in the 3D world)."),
    ("Settled", "A bet is settled when its question is decided and it pays out, or not."),
    ("The risk manager", "A safety check that stops new bets when a rule's own record shows it losing money."),
    ("Hard limits", ("Caps in the bot's settings, checked before every bet: how much can be in bets at once, and how "
                     "much can be lost before it stops.")),
    ("Receipts", ("The tamper-proof record: every decision is sealed the moment it happens, so any later change would "
                  "show.")),
    ("The vault", ("In the 3D world, the vault stands for the Solana bot's money; its sign says if it is real or "
                   "pretend.")),
    ("Trend desk", ("A practice desk that holds Bitcoin, Ether or Solana only while each is above its 50-day "
                    "average price.")),
)

#: The experience state (the report cards) is re-read at most this often.
EXPERIENCE_TTL_S = 60.0
#: The experience module itself, as Python names it when it is absent.
_EXPERIENCE_MODULES = ("nightcrawler.experience", "nightcrawler.experience.state")
#: The static playbook (generated from docs/EXPERIENCE_GROUNDED.md by scripts/gen_playbook.py).
PLAYBOOK_PATH = Path(__file__).resolve().parent / "experience" / "playbook.json"
#: docs/EXPERIENCE.md §8.2: the last line of the team's headline, always.
EXPERIENCE_CAVEAT = "Avoiding losses is not the same as making money."
#: The money line until the Coach itself has shown a strategy that makes money on coins it never saw.
EXPERIENCE_MONEY_LINE = "Making money: not shown yet — holding cash."
#: Coach card states that let the experience state word the money line itself (LEARNING §9).
_MONEY_STATES = ("paper_champion", "live_ready", "live")
#: The card kind of each member (docs/EXPERIENCE.md §5.1): only "chance" cards can show skill.
EXPERIENCE_KINDS = {"crawler": "bar", "cocoon": "chance", "strategy": "chance", "radar": "chance", "judge": "chance",
                    "broker": "bar", "risk": "bar", "receipts": "self_check", "coach": "self_check"}
#: The chip word of each label, per card kind (§5.1). A self-check is never green.
EXPERIENCE_CHIPS = {
    "chance": {"not_measured": "Not measured", "not_enough": "Collecting", "no_skill_yet": "No skill yet",
               "skilled": "Skill shown", "worse": "Worse than chance"},
    "bar": {"not_measured": "Not measured", "not_enough": "Collecting", "meets_bar": "Meets the bar",
            "below_bar": "Below the bar"},
    "self_check": {"not_built": "Not built yet", "checks_pass": "Checks pass", "check_failed": "Check failed"},
}
#: Risk's bar is a tolerance (§5.1).
_RISK_CHIPS = {"meets_bar": "Within tolerance", "below_bar": "Over tolerance"}
#: The good side of each bar (§5.2): coverage must reach its bar; shortfall and ruin must stay under theirs.
_BAR_GOOD_ABOVE = {"crawler": True, "broker": False, "risk": False}
#: Cocoon, Strategy, Radar and Jev: the cards that can show skill.
SKILL_MEMBERS = sum(kind == "chance" for kind in EXPERIENCE_KINDS.values())
_XP_UNITS = ("pp", "share", "ratio", "count", "s")
_XP_LESSON_KEYS = ("open", "testing", "adopted", "rejected")
_XP_PLAYBOOK_KEYS = ("validated", "rejected", "in_bot_contradicted", "in_bot_unsupported", "testing")
_XP_FALSE_KEEP = "1 in 10"
_XP_WORD = re.compile(r"[a-z][a-z0-9_]{0,29}")
_XP_HEX = re.compile(r"[0-9a-f]{1,12}")
XP_METRICS_MAX = 3
XP_LIST_MAX = 3  # loss types this week and lessons on the page
XP_TREND_MAX = 8  # weeks
XP_NAMES_MAX = 9
XP_LINE_MAX = 320  # a card's plain-words sentence
XP_COUNT_MAX = 10**9
XP_NUM_MAX = 1e9

#: Why a position was closed (``Position.exit_reason``), in plain words.
EXIT_WORDS = {
    "stop_loss": "Stop-loss: cut the loss", "trailing_stop": "Sold after the price fell from its high",
    "time_stop": "Time limit reached", "take_profit_partial": "Took profit", "kill_switch": "Kill switch: sold all",
    "manual": "Sold by hand",
}
_CARD_ALIASES = {
    "variants": ("variants", "top_variants"), "data": ("data", "data_line"),
    "reason": ("paper_matches_backtest_reason", "paper_reason"),
    "name": ("name", "id"), "n": ("n", "trades", "n_trades"), "avg": ("avg", "average"),
    "proof": ("proof", "proof_progress"),
}


# =========================================================================== helpers


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _num(value: Any) -> float | None:
    """A finite number (bool is not a number), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _pct(part: float | None, whole: float | None) -> float | None:
    return part / whole * 100.0 if part is not None and whole else None


def _times(a: float | None, b: float | None) -> float | None:
    return a * b if a is not None and b is not None else None


def _first(mapping: Mapping[str, Any], key: str) -> Any:
    return next((mapping[k] for k in _CARD_ALIASES[key] if k in mapping), None)


def _short(mint: str) -> str:
    return f"{mint[:4]}…{mint[-4:]}" if len(mint) > 12 else mint


class _Text:
    """Redact secrets FIRST, then clip, so a clipped secret can never slip past the scrub."""

    def __init__(self, settings: Settings) -> None:
        self.secrets = tuple(settings.secret_values())

    def __call__(self, value: Any, limit: int = TEXT_MAX) -> str:
        return _clip(redact_text(str(value), self.secrets), limit)

    def opt(self, value: Any, limit: int = TEXT_MAX) -> str | None:
        """Non-empty strings only, else None."""
        return self(value.strip(), limit) if isinstance(value, str) and value.strip() else None


# =========================================================================== learning card


def learning_card(settings: Settings, now: float, ledger: Any, memory: dict[str, Any] | None = None
                  ) -> dict[str, Any]:
    """The Coach's learning card, sanitized (schema in the module docstring): a real card, a "not installed"
    card or a "failed" card. Never raises. ``memory`` (kept between requests) caches it for
    :data:`LEARNING_TTL_S`."""
    cached = memory.get("learning") if memory is not None else None
    if cached is not None and 0 <= now - cached[0] < LEARNING_TTL_S:
        return dict(cached[1])
    outcome, raw = _load_card(settings, now)
    sanitized = _sanitize(raw, _Text(settings), now) if outcome == "ok" else None
    if outcome == "ok" and sanitized is None:
        log.warning("learning_card_invalid type=%s", type(raw).__name__)
    if outcome == "missing":
        card = _missing(now, ledger)
    else:
        card = sanitized or _failed()
    if memory is not None:
        memory["learning"] = (now, card)
    return dict(card)


def _load_card(settings: Settings, now: float) -> tuple[str, Any]:
    """``("ok", raw card)``, ``("missing", None)`` when the module is not installed, or ``("error", None)``."""
    try:
        from nightcrawler.learn.card import learning_card_state  # built on another branch; may be absent
    except ModuleNotFoundError as exc:
        if exc.name in _LEARN_MODULES:
            return "missing", None
        log.warning("learning_card_failed error=%s", type(exc).__name__)  # installed, but its import broke
        return "error", None
    except ImportError as exc:
        log.warning("learning_card_failed error=%s", type(exc).__name__)
        return "error", None
    try:
        return "ok", learning_card_state(settings, now)
    except Exception as exc:  # a broken learning module must never take the page down
        log.warning("learning_card_failed error=%s", type(exc).__name__)
        return "error", None


def _sanitize(raw: Any, text: _Text, now: float) -> dict[str, Any] | None:
    """The card's known keys, type-checked; None (a failure) unless it has a headline or a state."""
    if not isinstance(raw, Mapping):
        return None
    state, headline = text.opt(raw.get("state"), 60), text.opt(raw.get("headline"))
    if headline is None and state is None:
        return None
    champion = raw.get("champion")
    if isinstance(champion, Mapping):
        champion = champion.get("name")
    variants = _first(raw, "variants")
    items = variants if isinstance(variants, list) else []
    kept = [v for v in (_variant(item, text) for item in items) if v is not None]
    updated_at = _num(raw.get("updated_at"))
    return {
        "source": "card",
        "state": state,
        "headline": headline if headline is not None else f"Learning stage: {state}",
        "variants": kept[:VARIANTS_MAX],
        "data": text.opt(_first(raw, "data"), 200),
        "champion": text.opt(champion, 60),
        "champion_passed_locked_test": raw.get("champion_passed_locked_test") is True,
        "paper_matches_backtest": raw.get("paper_matches_backtest") is True,
        "paper_matches_backtest_reason": text.opt(_first(raw, "reason")),
        "can_stop_trading": raw.get("can_stop_trading") is True,
        # a stamp from the future (a millisecond epoch, say) would keep the Coach "Working" forever
        "updated_at": updated_at if updated_at is not None and updated_at <= now + FUTURE_SKEW_S else None,
    }


def _variant(item: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    name = text.opt(_first(item, "name"), 40)
    if name is None:
        return None
    n = _first(item, "n")
    avg, proof = _num(_first(item, "avg")), _num(_first(item, "proof"))
    return {"name": name,
            "n": n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None,
            "avg": avg if avg is not None and abs(avg) < 1e6 else None,
            "proof": min(1.0, max(0.0, proof)) if proof is not None else None}


def _empty_card(source: str, headline: str, data: str | None) -> dict[str, Any]:
    return {"source": source, "state": None, "headline": headline, "variants": [], "data": data, "champion": None,
            "champion_passed_locked_test": False, "paper_matches_backtest": False,
            "paper_matches_backtest_reason": None, "can_stop_trading": False, "updated_at": None}


def _missing(now: float, ledger: Any) -> dict[str, Any]:
    """The learning module is not installed: say so (day N since the first receipt)."""
    first = ledger.receipts(after_seq=0, limit=1)
    day = int(max(0.0, now - first[0].ts) // DAY_S) + 1 if first else 1
    return _empty_card("missing", "Not installed yet: nothing learns by itself in this version.",
                       f"The bot keeps every record from day 1 (today is day {day}) for the Coach to learn from "
                       "once it is added.")


def _failed() -> dict[str, Any]:
    """The learning module raised or returned something that is not a card (details in the logs)."""
    return _empty_card("error", "The learning system failed: see the logs.", None)


# =========================================================================== experience (report cards)


class _Refused(ValueError):
    """The experience state breaks a rule of the §9 schema or an honesty rule of §5.1: shown as an error."""


def experience_card(settings: Settings, now: float, card: Mapping[str, Any], memory: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """The team's report cards for ``/api/page.experience`` (schema and rules in the module docstring): a sanitized
    state, a "not installed" one or a "failed" one. ``card`` is the sanitized learning card (the money line follows
    the Coach). Never raises. ``memory`` (kept between requests) caches what was read for
    :data:`EXPERIENCE_TTL_S`."""
    cached = memory.get("experience") if memory is not None else None
    if cached is not None and 0 <= now - cached[0] < EXPERIENCE_TTL_S:
        outcome, raw = cached[1]
    else:
        outcome, raw = _load_experience(settings, now)
        if memory is not None:
            memory["experience"] = (now, (outcome, raw))
    static = _static_playbook(str(PLAYBOOK_PATH))
    if outcome != "ok":
        return _xp_empty(outcome, static)
    coach = card.get("state") if card.get("source") == "card" else None
    try:
        return _xp_state(raw, _Text(settings), now, live=settings.is_live, coach_state=coach, static=static)
    except _Refused as exc:
        log.warning("experience_state_refused reason=%s", exc)
    except Exception as exc:  # a strange object from another team's module must never take the page down
        log.warning("experience_state_failed error=%s", type(exc).__name__)
    return _xp_empty("error", static)


def _load_experience(settings: Settings, now: float) -> tuple[str, Any]:
    """``("ok", raw state)``, ``("missing", None)`` when the module is not installed, or ``("error", None)``."""
    try:
        from nightcrawler.experience.state import experience_state  # built by another team; may be absent
    except ModuleNotFoundError as exc:
        if exc.name in _EXPERIENCE_MODULES:
            return "missing", None
        log.warning("experience_state_failed error=%s", type(exc).__name__)  # installed, but its import broke
        return "error", None
    except ImportError as exc:
        log.warning("experience_state_failed error=%s", type(exc).__name__)
        return "error", None
    try:
        return "ok", experience_state(settings, now)
    except Exception as exc:  # a broken experience module must never take the page down
        log.warning("experience_state_failed error=%s", type(exc).__name__)
        return "error", None


@functools.lru_cache(maxsize=4)
def _static_playbook(path: str) -> dict[str, Any]:
    """The playbook counts by initial status, from the static file (read once per process); null when unreadable:
    "0 rules contradicted" would be a false claim."""
    try:
        rules = json.loads(Path(path).read_text(encoding="utf-8"))["rules"]
        statuses = Counter(rule["status"] for rule in rules)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("playbook_unreadable error=%s", type(exc).__name__)
        return {**dict.fromkeys(_XP_PLAYBOOK_KEYS), "false_keep_bound": _XP_FALSE_KEEP}
    return {**{key: statuses.get(key, 0) for key in _XP_PLAYBOOK_KEYS}, "false_keep_bound": _XP_FALSE_KEEP}


def _xp_empty(source: str, playbook: Mapping[str, Any]) -> dict[str, Any]:
    return {"source": source, "headline": ["", ""], "bars_line": "", "money_line": "", "caveat": EXPERIENCE_CAVEAT,
            "team": {"graded": None, "days": None, "practised": None, "practised_window": "", "skills_shown": None,
                     "skills_measurable": SKILL_MEMBERS, "collecting": None, "not_measured": [], "updated_at": None},
            "members": {}, "loss_types_week": [], "lessons": [], "playbook": dict(playbook)}


def _count(value: Any) -> int | None:
    """A whole number in [0, 10**9] (bool is not a number), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and 0 <= value <= XP_COUNT_MAX else None


def _xp_num(value: Any) -> float | None:
    number = _num(value)
    return number if number is not None and abs(number) < XP_NUM_MAX else None


def _xp_str(text: _Text, value: Any, limit: int = TEXT_MAX) -> str:
    return text.opt(value, limit) or ""


def _xp_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _xp_map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _xp_state(raw: Any, text: _Text, now: float, *, live: bool, coach_state: Any,
              static: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _Refused("not a mapping")
    if raw.get("source") in ("missing", "error"):  # the module itself says it has nothing (yet)
        return _xp_empty(raw["source"], static)
    members_raw = raw.get("members")
    if not isinstance(members_raw, Mapping):
        raise _Refused("members")
    members = {}
    for mid, _, _ in MEMBERS:
        if mid not in EXPERIENCE_KINDS:
            continue  # a desk the report cards do not grade (yet), e.g. the Polymarket paper desk
        key = "jev" if mid == "judge" and mid not in members_raw and "jev" in members_raw else mid
        if key in members_raw:
            members[mid] = _xp_member(mid, members_raw[key], text, live=live)
    headline = raw.get("headline")
    lines = [_xp_str(text, line) for line in headline[:2]] if isinstance(headline, list) else []
    lines += [""] * (2 - len(lines))
    if not members and not any(lines):
        raise _Refused("empty")
    team = _xp_team(raw.get("team"), members, text, now)
    money = _xp_str(text, raw.get("money_line")) if coach_state in _MONEY_STATES else ""
    return {
        "source": "state", "headline": lines, "bars_line": _xp_str(text, raw.get("bars_line")),
        "money_line": money or EXPERIENCE_MONEY_LINE, "caveat": EXPERIENCE_CAVEAT, "team": team, "members": members,
        "loss_types_week": _xp_items(raw.get("loss_types_week"), _xp_loss, text),
        "lessons": _xp_items(raw.get("lessons"), _xp_lesson, text),
        "playbook": _xp_playbook(raw.get("playbook"), static, text),
    }


def _xp_member(mid: str, raw: Any, text: _Text, *, live: bool) -> dict[str, Any]:
    kind = EXPERIENCE_KINDS[mid]
    if not isinstance(raw, Mapping):
        raise _Refused(f"member={mid}")
    label = raw.get("label")
    if raw.get("kind") != kind or not isinstance(label, str) or label not in EXPERIENCE_CHIPS[kind]:
        raise _Refused(f"kind_or_label member={mid}")
    items = _xp_list(raw.get("metrics"))
    _xp_check_claim(mid, kind, label, _xp_metric(items[0], text) if items else None, live=live)
    metrics = [m for m in (_xp_metric(item, text) for item in items[:XP_METRICS_MAX]) if m is not None]
    lessons = _xp_map(raw.get("lessons"))
    budget = _xp_num(raw.get("budget_left"))
    chip = _RISK_CHIPS[label] if mid == "risk" and label in _RISK_CHIPS else EXPERIENCE_CHIPS[kind][label]
    return {
        "kind": kind, "label": label, "chip": chip,
        "line": _xp_str(text, raw.get("line"), XP_LINE_MAX), "graded": _count(raw.get("graded")),
        "days": _count(raw.get("days")), "practised": _count(raw.get("practised")), "metrics": metrics,
        "exam": _xp_exam(raw.get("exam"), text), "trend": _xp_trend(raw.get("trend")),
        "version_line": _xp_str(text, raw.get("version_line")), "independent": _xp_str(text, raw.get("independent")),
        "lessons": {key: _count(lessons.get(key)) or 0 for key in _XP_LESSON_KEYS},
        "coverage": _xp_str(text, raw.get("coverage")),
        "budget_left": budget if budget is not None and 0.0 <= budget <= 1.0 else None,
    }


def _xp_check_claim(mid: str, kind: str, label: str, primary: dict[str, Any] | None, *, live: bool) -> None:
    """Green and "worse" claims need the primary band on one side of the baseline or bar (§5.1); on paper the
    Broker is never graded (§5.2: the paper fill and the cost model share the same haircut by construction)."""
    if mid == "broker" and not live and label != "not_measured":
        raise _Refused("broker_graded_on_paper")
    if label not in ("skilled", "worse", "meets_bar"):
        return
    lo, hi, base = (primary or {}).get("lo"), (primary or {}).get("hi"), (primary or {}).get("baseline")
    if lo is None or hi is None or base is None:
        raise _Refused(f"claim_without_band member={mid}")
    if label == "skilled":
        backed = lo > base
    elif label == "worse":
        backed = hi < base
    else:
        backed = lo >= base if _BAR_GOOD_ABOVE[mid] else hi <= base
    if not backed:
        raise _Refused(f"claim_not_backed member={mid}")


def _xp_metric(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or raw.get("unit") not in _XP_UNITS:
        return None
    name = text.opt(raw.get("name"), 60)
    if name is None:
        return None
    lo, hi = _xp_num(raw.get("lo")), _xp_num(raw.get("hi"))
    if lo is None or hi is None or lo > hi:  # half a band, or an upside-down one, is no band
        lo = hi = None
    return {"name": name, "value": _xp_num(raw.get("value")), "lo": lo, "hi": hi,
            "baseline": _xp_num(raw.get("baseline")), "unit": raw["unit"], "text": _xp_str(text, raw.get("text"))}


def _xp_exam(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    result = text.opt(raw.get("result"), 30)
    if result is None:
        return None
    version = raw.get("version12")
    return {"split": _xp_str(text, raw.get("split"), 20),
            "version12": version if isinstance(version, str) and _XP_HEX.fullmatch(version) else "",
            "date": _xp_str(text, raw.get("date"), 20), "result": result, "current": raw.get("current") is True}


def _xp_trend(raw: Any) -> list[list[float | None]]:
    """Weekly ``[week_start, value, lo, hi]`` of the primary metric, the last :data:`XP_TREND_MAX` weeks."""
    weeks = []
    for item in _xp_list(raw):
        if not isinstance(item, list) or len(item) != 4:
            continue
        start, value = _num(item[0]), _xp_num(item[1])  # a week's start is an epoch, not a metric value
        if start is None or value is None:
            continue
        lo, hi = _xp_num(item[2]), _xp_num(item[3])
        weeks.append([start, value, *((lo, hi) if lo is not None and hi is not None and lo <= hi else (None, None))])
    return weeks[-XP_TREND_MAX:]


def _xp_team(raw: Any, members: Mapping[str, Mapping[str, Any]], text: _Text, now: float) -> dict[str, Any]:
    team = _xp_map(raw)
    claimed = _count(team.get("skills_shown"))
    graded = [m for m in members.values() if m["kind"] == "chance"]
    shown = sum(m["label"] == "skilled" for m in graded) if graded else claimed
    if claimed is not None and claimed != shown:  # the headline's count would disagree with the chips
        raise _Refused("skills_shown")
    names = _xp_list(team.get("not_measured"))
    updated = _num(team.get("updated_at"))
    return {
        "graded": _count(team.get("graded")), "days": _count(team.get("days")),
        "practised": _count(team.get("practised")),
        "practised_window": _xp_str(text, team.get("practised_window"), 60), "skills_shown": shown,
        "skills_measurable": SKILL_MEMBERS, "collecting": _count(team.get("collecting")),
        "not_measured": [n for n in (text.opt(name, 40) for name in names[:XP_NAMES_MAX]) if n is not None],
        "updated_at": updated if updated is not None and updated <= now + FUTURE_SKEW_S else None,
    }


def _xp_items(raw: Any, keep: Callable[[Any, _Text], dict[str, Any] | None], text: _Text) -> list[dict[str, Any]]:
    """The first :data:`XP_LIST_MAX` well-formed items of a list (the rest is never even looked at)."""
    kept = (item for item in (keep(x, text) for x in _xp_list(raw)) if item is not None)
    return list(itertools.islice(kept, XP_LIST_MAX))


def _xp_loss(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("type"), str) or not _XP_WORD.fullmatch(raw["type"]):
        return None
    n, expected = _count(raw.get("n")), _xp_num(raw.get("expected"))
    if n is None:
        return None
    return {"type": raw["type"], "n": n, "expected": expected if expected is not None and expected >= 0 else None,
            "text": _xp_str(text, raw.get("text"))}


def _xp_lesson(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    status, words = raw.get("status"), _xp_str(text, raw.get("text"))
    lesson_id = _xp_str(text, raw.get("id"), 40)
    if not isinstance(status, str) or not _XP_WORD.fullmatch(status) or not (words or lesson_id):
        return None
    return {"id": lesson_id, "status": status, "text": words}


def _xp_playbook(raw: Any, static: Mapping[str, Any], text: _Text) -> dict[str, Any]:
    book = _xp_map(raw)
    counts = {key: _count(book.get(key)) for key in _XP_PLAYBOOK_KEYS}
    if all(v is None for v in counts.values()):
        return dict(static)
    return {**counts, "false_keep_bound": _xp_str(text, book.get("false_keep_bound"), 20) or _XP_FALSE_KEEP}


# =========================================================================== sections


def _latest_point(ledger: Any, mode: str) -> EquityPoint | None:
    """The newest equity snapshot when it belongs to ``mode`` (what ``build_state`` shows), else None."""
    point = ledger.latest_equity()
    return point if isinstance(point, EquityPoint) and point.mode == mode else None


def _money(settings: Settings, eq: dict[str, Any], point: EquityPoint | None,
           withdrawn: tuple[int, int] = (0, 0), desk: dict[str, Any] | None = None,
           trend: dict[str, Any] | None = None) -> dict[str, Any]:
    """``withdrawn``: live SOL (all time, today) sent back to the owner with WITHDRAW_TO - added back to the
    results, so taking money out never reads as a trading loss. ``desk``: :func:`polymarket_desk`, carried under
    ``polymarket`` apart from every SOL figure (never added to them); ``trend``: :func:`trend_desk`, likewise."""
    sol, sol_usd = eq["sol"], eq["sol_usd"]
    total, today = eq["pnl_total_sol"], eq["pnl_today_sol"]
    since_usd = eq["pnl_total_trading_usd"]
    out_total, out_today = (w / LAMPORTS_PER_SOL for w in withdrawn) if settings.is_live else (0.0, 0.0)
    base_total = sol - total if sol is not None and total is not None else None
    base_today = sol - today if sol is not None and today is not None else None
    if out_total and total is not None:
        total = total + out_total
        since_usd = _times(total, sol_usd)
    if out_today and today is not None:
        today = today + out_today
    curve = eq["curve"]
    span = curve[-1][0] - curve[0][0] if len(curve) >= 2 else 0.0
    return {
        "label": _money_label(settings),
        "usd": eq["usd"], "start_usd": eq["start_usd"], "sol": sol, "sol_usd": sol_usd,
        "withdrawn_sol": out_total or None,
        "since_start": {"usd": since_usd, "pct": _pct(total, base_total)},
        "today": {"usd": _times(today, sol_usd), "pct": _pct(today, base_today)},
        "sol_price_effect_usd": eq["sol_price_effect_usd"],
        "curve": curve, "chart_ready": span >= CHART_MIN_SPAN_S,
        "as_of": point.ts if point is not None else (curve[-1][0] if curve else None),
        "polymarket": desk,
        "trend": trend,
    }


def _withdrawn(ledger: Any, settings: Settings, point: EquityPoint | None, now: float) -> tuple[int, int]:
    """Live SOL sent back to the owner that the latest equity point ``point`` already reflects ``(since the
    start, since today's first point)`` - a later withdrawal is not in that point yet (it would count twice)."""
    if not settings.is_live or point is None or not ledger.get_kv("withdraw.totals"):
        return 0, 0
    first = next((p for p in ledger.equity_series(since=now - now % 86_400) if p.mode == point.mode), None)
    return withdrawn_lamports(ledger, point.ts, first.ts if first is not None else None)


def _money_label(settings: Settings) -> str:
    """The money card's label: the page must always make clear when the money is pretend."""
    return REAL_LABEL if settings.is_live else PAPER_LABEL


def _dollars(value: float) -> str:
    return f"${abs(value):,.2f}"


def _signed(value: float) -> str:
    """``+$1.20`` / ``−$1,345.53`` / ``$0.00``, to the cent, as the page's script prints a signed dollar figure."""
    cents = round(value, 2)
    return ("+" if cents > 0 else _MINUS if cents < 0 else "") + _dollars(cents)


def _verb(value: float) -> str:
    return "lost" if value < 0 else "made"


def _run_started(ledger: Any, state: Mapping[str, Any]) -> float | None:
    """When the bot first ran on this volume: the ledger's first record (the first boot's receipt) or the engine's
    start (kv ``engine.started_at``: the current process only), whichever is earlier; None until either exists."""
    first = ledger.receipts(after_seq=0, limit=1)
    stamps = [_num(first[0].ts)] if first else []
    stamps.append(_num(_xp_map(state.get("engine")).get("started_at")))
    known = [ts for ts in stamps if ts is not None]
    return min(known) if known else None


# =========================================================================== the Polymarket desk


def polymarket_desk(settings: Settings, now: float) -> dict[str, Any] | None:
    """The Polymarket desk's books for the money card and the town (POLYMARKET in the module docstring), paper and
    real kept apart and never added together. None when the desk is off (``POLYDESK_ENABLED``) or its state cannot
    be read: nothing is shown rather than a made-up zero. Never raises."""
    if not settings.polydesk_enabled:
        return None
    try:
        desk = panel_state(settings, now)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:  # a malformed state file: never take the page down
        log.warning("polydesk_panel_failed error=%s", type(exc).__name__)
        return None
    raw_real, venue, balance = _xp_map(desk.get("real")), _xp_map(desk.get("exchange")), _xp_map(desk.get("balance"))
    real = _book(raw_real, REAL_LABEL)
    real.update({
        "at_risk_usd": _num(raw_real.get("at_risk_usd")) or 0.0,
        "contracts": _num(venue.get("contracts")), "cost_usd": _num(venue.get("cost_usd")),
        "value_usd": _num(venue.get("value_usd")), "venue_at": _num(venue.get("at")),
        "cash_usd": _num(balance.get("cash")), "cash_at": _num(balance.get("at")),
        # orders the venue has not confirmed yet (open real money until its book says) and the loss stops' room
        "pending": _count(raw_real.get("pending")) or 0, "pending_usd": _num(raw_real.get("pending_usd")) or 0.0,
        "stop_room_usd": _num(raw_real.get("stop_room_usd")),
        "stop_room_limit": raw_real.get("stop_room_limit") if raw_real.get("stop_room_limit") in ("day", "total")
        else None,
    })
    live = desk.get("mode") == "live"
    return {
        "mode": "live" if live else "paper", "label": REAL_LABEL if live else PAPER_LABEL,
        "as_of": _num(desk.get("last_ok")),
        # the desk's own word on live mode: why it is on paper although live was asked for (a rejected key, the
        # total-loss cap), or the day's loss cap; redacted, then clipped
        "status": _Text(settings).opt(desk.get("live_status")),
        "paper": _book(_xp_map(desk.get("paper")), PAPER_LABEL),
        # the venue's cash alone (a key, no contracts) is real money to show, but not a real book for the town
        "real": real if _real_book(real) or real["cash_usd"] is not None else None,
        "real_closed": _real_closed(desk.get("real_closed")),
        "guard": _desk_guard(desk.get("guard")),
        # its newest settled REAL-money bets from its whole event log (the team row keeps only the last five events,
        # and one round can settle several bets and add a pause and a lesson): the 3D world's replays
        "settled_real": _settled_real(desk.get("events"), _Text(settings)),
        "skips": _desk_skips(desk.get("skips")),
        "sports": _desk_sports(desk.get("sports")),
        "real_sports_allowed": sorted({s for s in desk.get("real_sports_allowed") or [] if s in SPORT_HISTORY}),
        "arbs": _desk_arbs(desk.get("arbs"), _Text(settings)),
    }


#: ``money.polymarket.arbs``' whole-number counts (``polydesk.arbs_view``).
ARB_COUNTS = ("today_seen", "today_bought", "today_checked", "today_still_there", "sets_paper", "open_sets",
              "settled_sets", "broken")


def _desk_arbs(raw: Any, text: _Text) -> dict[str, Any]:
    """``money.polymarket.arbs``: the no-lose check (``polydesk.arbs_view``, practice only), type-checked: whole
    counts (a missing one is zero), the paper sets' P&L, and the newest arbs (a name redacted then clipped, the total
    and edge as numbers, the smallest ask size or null, still there a round later true / false / null)."""
    a = _xp_map(raw)
    last = []
    for row in _xp_list(a.get("last"))[:ARB_SHOWN]:
        r = _xp_map(row)
        total, edge, there = _num(r.get("total")), _num(r.get("edge")), r.get("still_there")
        if total is None or edge is None or not isinstance(r.get("name"), str):
            continue
        last.append({"name": text(r["name"], 80), "total": total, "edge": edge, "min_size": _num(r.get("min_size")),
                     "still_there": there if isinstance(there, bool) else None})
    return {**{key: _count(a.get(key)) or 0 for key in ARB_COUNTS}, "pnl_usd": _num(a.get("pnl_usd")) or 0.0,
            "last": last}


def _desk_skips(raw: Any) -> dict[str, dict[str, int]]:
    """``money.polymarket.skips``: today's skip counts (``polydesk.skips_view``), type-checked: the desk's own
    reasons (:data:`nightcrawler.polydesk.SKIP_REASONS`) and sports only, each a whole number above zero."""
    skips = _xp_map(raw)

    def counts(value: Any, known: Any) -> dict[str, int]:
        out: dict[str, int] = {}
        for key, n in _xp_map(value).items():
            got = _count(n)
            if got and key in known:
                out[str(key)] = got
        return out

    return {"counts": counts(skips.get("counts"), SKIP_REASONS), "sports": counts(skips.get("sports"), SPORT_HISTORY)}


def _desk_sports(raw: Any) -> list[dict[str, Any]]:
    """``money.polymarket.sports``: each sport (``polydesk.sports_view``), type-checked: whether real money may bet it,
    the history's verdict and reason, the practice record (or null) and whether it is flagged."""
    out: list[dict[str, Any]] = []
    for row in raw if isinstance(raw, list) else []:
        r = _xp_map(row)
        if r.get("sport") not in SPORT_HISTORY or r.get("real") not in ("allowed", "blocked"):
            continue
        paper = _xp_map(r.get("paper"))
        practice = None
        if paper and paper.get("verdict") in GUARD_VERDICTS:
            practice = {"settled": _count(paper.get("settled")) or 0, "won": _count(paper.get("won")) or 0,
                        "pnl_usd": _num(paper.get("pnl_usd")) or 0.0, "verdict": paper["verdict"],
                        "phrase": _clip(str(paper.get("phrase") or ""), 40)}
        out.append({"sport": r["sport"], "real": r["real"], "history": _clip(str(r.get("history") or ""), 40),
                    "why": _clip(str(r.get("why") or ""), TEXT_MAX), "paper": practice,
                    "flagged": r.get("flagged") is True})
    return out


def _settled_real(raw: Any, text: _Text) -> list[dict[str, Any]]:
    """``money.polymarket.settled_real``: the desk's own "Settled: … (real)" events (:data:`_REAL_SETTLED`), newest
    first, at most :data:`PLAIN_FINISHED_MAX`, each ``{ts, text}`` (the text redacted, then clipped); a practice
    settlement, a buy, a pause or a lesson is never one."""
    out: list[dict[str, Any]] = []
    for ev in raw if isinstance(raw, list) else []:
        if not isinstance(ev, Mapping) or not isinstance(ev.get("text"), str):
            continue
        ts, words = _num(ev.get("ts")), text(ev["text"].strip())
        if ts is not None and _REAL_SETTLED.fullmatch(words):
            out.append({"ts": ts, "text": words})
    out.sort(key=lambda e: -e["ts"])  # (stable: one round's settlements keep the desk's own order)
    return out[:PLAIN_FINISHED_MAX]


def _real_closed(raw: Any) -> list[dict[str, Any]]:
    """``money.polymarket.real_closed``: the desk's newest real settlements (panel ``real_closed``), type-checked:
    the question (clipped), when it settled, the result in dollars and whether it won."""
    out = []
    for row in raw if isinstance(raw, list) else []:
        r = _xp_map(row)
        pnl = _num(r.get("pnl_usd"))
        if pnl is None or not isinstance(r.get("won"), bool):
            continue
        out.append({"question": _clip(str(r.get("question") or ""), 80), "settled_at": _num(r.get("settled_at")),
                    "pnl_usd": pnl, "won": r["won"]})
    return out[:5]


def _desk_guard(raw: Any) -> dict[str, Any] | None:
    """``money.polymarket.guard``: the risk manager's verdict on the desk's current rule (``polydesk.guard_view``),
    type-checked: ``{verdict, reason, paused, since, line, on, candidate, real: {verdict, reason, paused, since,
    line}|null}`` (``since``: when the pause began, e.g. ``18:40 UTC``, or null); None without a paper verdict (an
    older state, a junk one)."""
    g = _xp_map(raw)

    def book(v: Mapping[str, Any]) -> dict[str, Any] | None:
        verdict = v.get("verdict")
        if verdict not in GUARD_VERDICTS:
            return None
        paused = v.get("paused") is True
        since = v.get("paused_since")
        return {"verdict": verdict, "reason": _clip(str(v.get("reason") or ""), TEXT_MAX), "paused": paused,
                "since": _clip(since, 40) if paused and isinstance(since, str) and since else None,
                "line": _clip(str(v.get("line") or ""), 3 * TEXT_MAX)}

    paper = book(_xp_map(g.get("paper")))
    if paper is None:
        return None
    return {**paper, "on": g.get("on") is not False, "candidate": isinstance(g.get("candidate"), Mapping),
            "real": book(_xp_map(g.get("real")))}


def _book(raw: Mapping[str, Any], label: str) -> dict[str, Any]:
    """One of the desk's two tallies (the panel's ``paper`` or ``real``), type-checked. The desk keeps these as
    running counts from zero, so a missing one is zero."""
    today = _xp_map(raw.get("today"))
    return {"label": label, "open": _count(raw.get("open")) or 0,
            "today_usd": _num(today.get("pnl_usd")) or 0.0, "since_start_usd": _num(raw.get("pnl_total_usd")) or 0.0,
            "settled_today": _count(today.get("settled")) or 0, "won_today": _count(today.get("won")) or 0,
            "settled_total": _count(raw.get("settled_total")) or 0, "won_total": _count(raw.get("won_total")) or 0}


def _real_book(real: Mapping[str, Any]) -> bool:
    """Real money in play: an open real position, a real settlement, a contract the venue's own book holds, or an
    order the venue has not confirmed yet."""
    return bool(real["open"] or real["settled_total"] or (real.get("contracts") or 0) > 0 or real.get("pending"))


def _desk_lines(desk: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``town.polymarket``: the desk's books (:func:`polymarket_desk`) in words, one line per kind of money, never
    added together; the real line only while the desk has a real book."""
    if desk is None:
        return None
    paper, real = desk["paper"], desk.get("real")
    line = (f"Polymarket desk (paper, pretend): today {_signed(paper['today_usd'])}, since start "
            f"{_signed(paper['since_start_usd'])}, {paper['open']} open")
    if desk.get("as_of") is None:
        line += "; no round finished yet"
    guard = _xp_map(desk.get("guard"))
    if guard.get("paused"):
        line += "; paused by the risk manager"
    out: dict[str, Any] = {"paper": {"label": PAPER_LABEL, "open": paper["open"], "today_usd": paper["today_usd"],
                                     "since_start_usd": paper["since_start_usd"], "line": line}, "real": None}
    if real is not None and _real_book(real):
        real_line = _real_line(real)
        if _xp_map(guard.get("real")).get("paused"):
            real_line += "; real buys paused by the risk manager"
        out["real"] = {"label": REAL_LABEL, "open": real["open"], "contracts": real["contracts"],
                       "cost_usd": real["cost_usd"], "value_usd": real["value_usd"], "today_usd": real["today_usd"],
                       "settled_today": real["settled_today"], "won_today": real["won_today"],
                       "since_start_usd": real["since_start_usd"], "cash_usd": real["cash_usd"],
                       "line": real_line}
    return out


def _real_line(real: Mapping[str, Any]) -> str:
    """The real line, e.g. ``Polymarket desk (REAL money): 8 contracts at the venue, cost $7.80, worth $7.95 now;
    settled today 0/0 won $0.00; since start +$0.50; cash at the venue $16.27``. A part the venue has not answered
    says so instead of showing a zero."""
    contracts, cost, value, cash = real["contracts"], real["cost_usd"], real["value_usd"], real["cash_usd"]
    if contracts is not None:
        venue = f"{contracts:g} contract{'' if contracts == 1 else 's'} at the venue"
        venue += f", cost {_dollars(cost)}" if cost is not None else ""
        venue += f", worth {_dollars(value)} now" if value is not None else ""
    else:
        venue = f"{real['open']} open ({_dollars(real['at_risk_usd'])} at risk), the venue's book not read yet"
    held = f"cash at the venue {_dollars(cash)}" if cash is not None else "cash at the venue not read yet"
    return (f"Polymarket desk (REAL money): {venue}; settled today {real['won_today']}/{real['settled_today']} won "
            f"{_signed(real['today_usd'])}; since start {_signed(real['since_start_usd'])}; {held}")


def _with_desk(made: str, income_today: float | None, desk: Mapping[str, Any], *, live: bool) -> str:
    """The town's sentence with the Polymarket desk's paper result beside the SOL bot's: the two desks are named
    apart and never added. Both pretend and both known, in one breath: "the Solana desk lost $3.18 and the
    Polymarket desk lost $1,345.53 today (paper money, pretend)"."""
    joiner = "; " if income_today is None else " and "
    if desk.get("as_of") is None:
        return f"{made}{joiner}the Polymarket desk has not finished a round yet (paper money, pretend)"
    poly = desk["paper"]["today_usd"]
    if income_today is not None and not live:
        return (f"the Solana desk {_verb(income_today)} {_dollars(income_today)} and the Polymarket desk "
                f"{_verb(poly)} {_dollars(poly)} today (paper money, pretend)")
    return f"{made}{joiner}the Polymarket desk {_verb(poly)} {_dollars(poly)} today (paper money, pretend)"


def _real_sentence(real: Mapping[str, Any]) -> str:
    """The desk's real money in the town's line: its own sentence, never part of the paper figures."""
    since = f"since start {_signed(real['since_start_usd'])}."
    if not real["settled_today"]:
        return f" Polymarket real money: nothing settled today; {since}"
    return (f" Polymarket real money: {_verb(real['today_usd'])} {_dollars(real['today_usd'])} today "
            f"({real['won_today']}/{real['settled_today']} won); {since}")


# =========================================================================== the trend desk


def trend_desk(settings: Settings, now: float) -> dict[str, Any] | None:
    """The trend desk's paper book for the money card (TREND in the module docstring), type-checked: its own figures,
    never added to anything else. None when the desk is off (``TRENDDESK_ENABLED``) or its state cannot be read or
    holds junk: nothing is shown rather than a made-up number. Never raises."""
    if not settings.trenddesk_enabled:
        return None
    try:
        raw = trenddesk.panel_state(settings, now)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:  # a malformed state file: never take the page down
        log.warning("trenddesk_panel_failed error=%s", type(exc).__name__)
        return None
    figures = {key: _num(raw.get(key)) for key in ("sleeve_usd", "equity_usd", "today_usd", "since_start_usd")}
    figures["hold_since_start_usd"] = _num(raw.get("bh_since_start_usd"))  # holding the three, bought on day one
    if any(value is None for value in figures.values()):
        return None
    lab = {"since_start_usd": _num(raw.get("lab_since_start_usd")),
           "hold_since_start_usd": _num(raw.get("lab_hold_since_start_usd"))}
    in_market = _xp_map(raw.get("in_market"))
    started, problem, reset = raw.get("started"), raw.get("problem"), raw.get("reset_from")
    return {"mode": "paper", "label": PAPER_LABEL, "as_of": _num(raw.get("as_of")), **figures,
            "in_market": {coin: in_market.get(coin) is True for coin in trenddesk.COINS},
            "started": started if isinstance(started, str) else None,
            "problem": _clip(problem, TEXT_MAX) if isinstance(problem, str) and problem else None,
            "lab": lab if all(value is not None for value in lab.values()) else None,
            "reset_from": _clip(reset, 80) if isinstance(reset, str) and reset else None}


def _trend_line(trend: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``town.trend``: the trend desk in one sentence, paper and pretend, its own figures only (never summed),
    against holding the three bought on day one and never touched; a record that replaced an unreadable one says
    so."""
    if trend is None:
        return None
    who = "Trend desk (paper, pretend)"
    if trend.get("reset_from"):
        who = f"Trend desk (paper, pretend; record restarted {trend.get('started') or 'today'})"
    if trend["as_of"] is None:
        first = (f"first booking at the close of {trend['started']} (UTC midnight)" if trend.get("started")
                 else "not started")
        line = f"{who}: {first}; nothing booked yet"
    else:
        line = (f"{who}: {trenddesk.in_out_text(trend['in_market'])}; since start "
                f"{_signed(trend['since_start_usd'])} vs holding the three (bought on day one, never touched) "
                f"{_signed(trend['hold_since_start_usd'])}")
    if trend.get("problem"):
        line += "; behind: the newest daily close is not booked yet"
    return {"line": line}


# =========================================================================== the town


def town_ledger(settings: Settings, money: Mapping[str, Any], judge: Mapping[str, Any] | None, now: float,
                started_at: float | None) -> dict[str, Any]:
    """The town's books (TOWN in the module docstring): what running the bot costs against what the desks made,
    today and since the start. ``money`` is the page's money card (its ``polymarket`` block, :func:`polymarket_desk`
    or absent, is the Polymarket desk: counted apart, in its own lines, never in the income figures), ``judge`` the
    ``judge`` block of ``/api/state`` (None, or missing or junk figures, count as nothing recorded), ``started_at``
    when the run began (None: not known). Never a made-up number: an unknown side is null and the line says so."""
    spend = _xp_map(judge)
    fixed_day = settings.town_railway_usd_month / TOWN_MONTH_DAYS
    uptime_s = max(0.0, now - started_at) if started_at is not None else None
    judge_total = max(0.0, _num(spend.get("cost_usd_total")) or 0.0)
    judge_today = _num(spend.get("cost_usd_today"))
    if judge_today is None:  # no figure for today: the total spread over the days run so far (at least one)
        judge_today = judge_total / max(1.0, (uptime_s or 0.0) / DAY_S)
    judge_today = max(0.0, judge_today)
    day_start = now - now % DAY_S
    since = max(day_start, started_at) if started_at is not None else day_start
    cost_per_day = fixed_day + judge_today
    cost_today = fixed_day * min(1.0, max(0.0, now - since) / DAY_S) + judge_today
    cost_since = fixed_day * uptime_s / DAY_S + judge_total if uptime_s is not None else None
    income_today = _num(_xp_map(money.get("today")).get("usd"))
    income_since = _num(_xp_map(money.get("since_start")).get("usd"))
    desk = money.get("polymarket")  # the Polymarket desk's books, or nothing: the desk is off
    trend = money.get("trend")  # the trend desk's paper book, or nothing
    if not (isinstance(trend, Mapping) and "as_of" in trend and isinstance(trend.get("in_market"), Mapping)):
        trend = None
    desk = desk if isinstance(desk, Mapping) and isinstance(desk.get("paper"), Mapping) else None
    kind = "real money" if settings.is_live else "paper money"
    who = "Solana desk" if desk is not None else "desks"
    if income_today is None:
        made = f"what the {who} made today ({kind}) is not known yet: no money check so far"
    else:
        made = f"the {who} {_verb(income_today)} {_dollars(income_today)} today ({kind})"
    if desk is not None:
        made = _with_desk(made, income_today, desk, live=settings.is_live)
    line = f"The town costs {_dollars(cost_per_day)} a day to run; {made}."
    guard = _xp_map(desk.get("guard")) if desk is not None else {}
    if guard.get("paused"):
        line += " The Polymarket desk is paused by the risk manager: its rule's record was losing money."
    elif _xp_map(guard.get("real")).get("paused"):
        line += " The Polymarket desk's real buys are paused by the risk manager: its real record was losing money."
    real = desk.get("real") if desk is not None else None
    if real is not None and _real_book(real):
        line += _real_sentence(real)
    if cost_since is None:
        line += " How long the town has been running is not known yet."
    return {
        "label": _money_label(settings),
        "cost_per_day_usd": cost_per_day,
        "cost_today_usd": cost_today,
        "cost_since_start_usd": cost_since,
        "income_today_usd": income_today,
        "income_since_start_usd": income_since,
        "covered_today": income_today >= cost_today if income_today is not None else None,
        "covered_since_start": (income_since >= cost_since if income_since is not None and cost_since is not None
                                else None),
        "line": line,
        "polymarket": _desk_lines(desk),
        "trend": _trend_line(trend),  # its own line: never in the income figures or the line above
    }


# =========================================================================== the town's goal (GOAL)

#: The readiness checklist's security steps, never listed in the goal's road (their state is not for the world).
GOAL_UNLISTED_STEPS = ("keys", "locked")
GOAL_UNLISTED_LABELS = tuple(CHECK_LABELS[k] for k in GOAL_UNLISTED_STEPS)


def _road_steps(ready: Mapping[str, Any]) -> list[Any]:
    """The checklist's counted steps (its first ``total`` items: the last item, the switch itself, is the action)."""
    items, total = _xp_list(ready.get("items")), _num(ready.get("total"))
    return items[:int(total)] if total is not None and total >= 0 else items


def goal_books(ledger: Any, settings: Settings, now: float) -> tuple[Any, list[float] | None]:
    """``(live_days, today_pnls)`` for :func:`goal_inputs`: the Polymarket desk's own real day book (its state file,
    read only: the books its daily stop uses; None while the desk is off or the file cannot be read) and today's real
    settlements' results in their order (the ``polydesk_settled`` receipts since the UTC day began; None on a read
    error). Never raises."""
    live_days: Any = None
    if settings.polydesk_enabled:
        try:
            live_days = load_state(state_path(settings)).get("live_days")
        except (KeyError, TypeError, ValueError, AttributeError, OSError):
            live_days = None
    pnls: list[float] | None
    try:
        rows = ledger._rows("SELECT payload FROM receipts WHERE kind = 'polydesk_settled' AND ts >= ? ORDER BY seq",
                            [now - now % DAY_S])
        pnls = [_num(_payload(row[0]).get("pnl_usd")) or 0.0 for row in rows]
    except (LedgerError, sqlite3.Error, AttributeError, LookupError, TypeError, ValueError) as exc:
        log.warning("town_goal_receipts_failed error=%s", type(exc).__name__)
        pnls = None
    return live_days, pnls


def goal_inputs(settings: Settings, page: Mapping[str, Any], now: float, *, live_days: Any,
                today_pnls: Any) -> dict[str, Any]:
    """What :mod:`nightcrawler.towngoal` reads (GOAL in the module docstring): this page's own figures (``page``: the
    assembled ``/api/page``), the desk's real day book and today's real settlements (:func:`goal_books`) and the
    settings the words quote (the target, the desk's contracts a bet, its price and its hard limits). Read only:
    nothing here reaches a desk."""
    money = _xp_map(page.get("money"))
    desk = _xp_map(money.get("polymarket"))
    real = desk.get("real") if isinstance(desk.get("real"), Mapping) else None
    plain = _xp_map(page.get("plain"))
    preal = _xp_map(plain.get("real"))
    members = [_xp_map(m) for m in _xp_list(_xp_map(page.get("team")).get("members"))]
    risk = next((m for m in members if m.get("id") == "risk"), {})
    radar = next((m for m in members if m.get("id") == "radar"), {})
    caps = _xp_map(risk.get("risk_wall")).get("real_caps")
    guard = _xp_map(_xp_map(desk.get("guard")).get("real"))
    trades = _xp_map(page.get("trades"))
    summary = _xp_map(trades.get("summary"))
    closed = _xp_list(trades.get("closed"))
    last = _xp_map(closed[0]) if closed else {}
    ready = _xp_map(page.get("ready"))
    receipts = _xp_map(page.get("receipts"))
    trend = _xp_map(money.get("trend"))
    live = settings.is_live
    paused = preal.get("paused")
    return {
        "target": towngoal.parse_goal(settings.town_goal_usd),
        "now": now, "day": utc_day(now),
        "real_on": preal.get("on") is True, "reported": preal.get("reported") is not False,
        "paused": paused if isinstance(paused, str) and paused else None,
        "paused_kind": preal.get("paused_kind"),
        "desk_mode": desk.get("mode"),
        "real": {key: real.get(key) for key in ("today_usd", "settled_today", "won_today", "since_start_usd",
                                                 "cash_usd", "cash_at")} if real is not None else None,
        "solana_live": live,
        "solana_today_usd": _num(_xp_map(money.get("today")).get("usd")) if live else None,
        "bill": _num(_xp_map(page.get("town")).get("cost_per_day_usd")),
        "caps": dict(caps) if isinstance(caps, Mapping) else None,
        "limits": {"open_max_usd": float(settings.polydesk_live_max_open_usd),
                   "day_max_usd": float(settings.polydesk_live_daily_loss_usd),
                   "total_max_usd": float(settings.polydesk_live_total_loss_usd)},
        "guard_real": {"verdict": guard.get("verdict"), "reason": guard.get("reason")} if guard else None,
        "rule_lab_passed": bool(RULE_LAB_PASSED),
        "contracts": float(settings.polydesk_live_contracts), "theta": float(settings.polydesk_theta),
        "live_days": live_days, "today_pnls": today_pnls,
        "first_real_ts": _num(_xp_map(summary.get("real")).get("since")),
        # the Solana bot's road to real money: the checklist's labels and ticks only, never a reason, and never its
        # security steps (the world is the page the owner shows friends: which of those is not done stays off it;
        # the count of steps done still counts them)
        "ready": {"done": ready.get("done"), "total": ready.get("total"),
                  "items": [{"label": _xp_map(i).get("label"), "done": _xp_map(i).get("done") is True}
                            for i in _road_steps(ready)
                            if _xp_map(i).get("id") not in GOAL_UNLISTED_STEPS
                            and _xp_map(i).get("label") not in GOAL_UNLISTED_LABELS]} if ready else None,
        "receipts": {key: receipts.get(key) for key in ("count", "verified", "first_bad_seq")},
        "trials_total": _xp_map(page.get("research")).get("trials_total"),
        "said_crawler": _xp_map(_xp_map(plain.get("said")).get("crawler")).get("text"),
        "radar_doing": radar.get("doing"),
        "last_closed": {key: last.get(key) for key in ("coin", "pnl_usd", "why")} if last else None,
        "trades_won": summary.get("won"), "trades_lost": summary.get("lost"),
        "practice_wallet_usd": None if live else _num(_xp_map(money.get("since_start")).get("usd")),
        # practice (pretend money): shown apart, never counted toward the goal
        "practice": {"solana_today_usd": None if live else _num(_xp_map(money.get("today")).get("usd")),
                     "polymarket_today_usd": _num(_xp_map(desk.get("paper")).get("today_usd")) if desk else None,
                     "trend_today_usd": _num(trend.get("today_usd")) if trend else None},
    }


def town_goal_block(settings: Settings, page: Mapping[str, Any], now: float, *, live_days: Any,
                    today_pnls: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(town.goal, plain.goal)`` (GOAL in the module docstring), worded with this page's own money formatters."""
    inputs = goal_inputs(settings, page, now, live_days=live_days, today_pnls=today_pnls)
    goal = towngoal.town_goal(inputs, whole=_limit)
    return goal, towngoal.goal_words(goal, inputs, dollars=_dollars, signed=_signed, limit=_limit)


def _coach(card: dict[str, Any], now: float) -> tuple[str, str]:
    if card["source"] == "missing":
        return "absent", "not built yet"
    if card["source"] == "error":
        return "blocked", "the learning system failed: see the logs"
    return derive_status(now, card["updated_at"], COACH_WINDOW_S,
                         waiting="collecting data: nothing to learn from yet" if card["state"] == "collecting"
                         else None, idle="no new lesson recently")


def _members(team: dict[str, Any], card: dict[str, Any], now: float) -> list[dict[str, Any]]:
    panels = {p["id"]: p for p in team["panels"]}
    out = []
    for mid, name, role in MEMBERS:
        if mid == "coach":
            status, why = _coach(card, now)
            out.append({"id": mid, "name": name, "role": role, "status": status, "why": why,
                        "doing": card["headline"], "last_activity": card["updated_at"], "events": []})
            continue
        p = panels[mid]
        last = p["last_activity"]  # never "last active 0 s ago" for a stamp from the future
        member = {"id": mid, "name": name, "role": role, "status": p["status"], "why": p["why"], "doing": p["doing"],
                  "last_activity": last if last is None or last <= now + FUTURE_SKEW_S else None,
                  "events": p["events"]}
        if p.get("bars"):
            member["bars"] = p["bars"]
        if isinstance(p.get("risk_wall"), dict):  # the risk member's gauge board numbers (the 3D world)
            member["risk_wall"] = dict(p["risk_wall"])
        if isinstance(p.get("positions"), list):  # the Polymarket desk's open positions (paper or real), capped
            member["positions"] = [
                {"question": str(x.get("question") or "")[:80], "side": str(x.get("side") or ""),
                 "p_in": x.get("p_in"), "category": str(x.get("category") or ""), "live": bool(x.get("live"))}
                for x in p["positions"][:10] if isinstance(x, dict)
            ]
            member["label"] = str(p.get("label") or "")
            member["open_real"] = int(p.get("open_real") or 0)  # real-money positions open (whole book)
            member["open_paper"] = int(p.get("open_paper") or 0)  # paper ones, e.g. running off after a switch
        out.append(member)
    return out


def _trades(ledger: Any, settings: Settings, state: dict[str, Any], text: _Text,
            desk: Mapping[str, Any] | None = None) -> dict[str, Any]:
    mode = "live" if settings.is_live else "paper"
    sol_usd = state["equity"]["sol_usd"]
    opened = [{"coin": text(p["symbol"] or _short(p["mint"]), COIN_MAX), "entry_usd": p["entry_price_usd"] or None,
               "now_usd": p["last_price_usd"], "pnl_usd": _times(p["unrealized_pnl_sol"], sol_usd),
               "pnl_pct": p["unrealized_pnl_pct"], "opened_at": p["opened_at"], "partial": p["partial_taken"],
               "foreign": bool(p.get("foreign_wallet"))}
              for p in state["positions"][:OPEN_MAX]]
    # every closed trade of this mode (the ledger already reads them all to filter the mode): the shelf counts them
    rows = ledger.positions(status="closed", mode=mode)
    rows.sort(key=lambda p: p.closed_at if p.closed_at is not None else p.opened_at, reverse=True)
    results = ["W" if (pnl := p.pnl_lamports()) > 0 else "L" if pnl < 0 else "E" for p in rows]
    closes = [p.closed_at for p in rows if p.closed_at is not None]
    summary = {"label": _money_label(settings), "won": results.count("W"), "lost": results.count("L"),
               "even": results.count("E"), "total": len(results), "since": min(closes) if closes else None,
               "order": "".join(results[:SHELF_MAX]), "real": _real_shelf(ledger, desk)}
    closed = []
    for p in rows[:CLOSED_MAX]:
        pnl = p.pnl_lamports() / LAMPORTS_PER_SOL
        reason = p.exit_reason or ""
        why = "Danger spotted, sold early" if reason.startswith("radar") else EXIT_WORDS.get(reason, "Sold")
        closed.append({"coin": text(p.symbol or _short(p.mint), COIN_MAX), "opened_at": p.opened_at,
                       "closed_at": p.closed_at, "pnl_usd": _times(pnl, sol_usd),
                       "pnl_pct": _pct(pnl, p.cost_lamports / LAMPORTS_PER_SOL),
                       "result": "won" if pnl > 0 else "lost" if pnl < 0 else "even", "why": text(why, WHY_MAX)})
    return {"open": opened, "closed": closed, "summary": summary, "max_open": settings.max_open_positions}


def _payload(text: Any) -> Mapping[str, Any]:
    """A receipt's JSON payload as a mapping; anything else (bad JSON, a list, a number) is an empty one."""
    try:
        return _xp_map(json.loads(text))
    except (TypeError, ValueError):
        return {}


def _real_shelf(ledger: Any, desk: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``trades.summary.real`` (TROPHIES in the module docstring): the Polymarket desk's real bets only, null unless the
    desk has a real book. Totals from the money card; the order of the real settlements from the receipts (newest
    first, at most :data:`SHELF_MAX`); the lines in the desk's own words."""
    real = _xp_map(desk.get("real")) if isinstance(desk, Mapping) else {}
    if not real or not _real_book(real):
        return None
    settled, won = _count(real.get("settled_total")) or 0, _count(real.get("won_total")) or 0
    rows = ledger._rows("SELECT ts, payload FROM receipts WHERE kind = 'polydesk_settled' ORDER BY seq DESC LIMIT ?",
                        [SHELF_MAX])
    order = "".join("W" if (_num(_payload(payload).get("pnl_usd")) or 0.0) > 0 else "L" for _, payload in rows)
    first = ledger._rows("SELECT ts FROM receipts WHERE kind = 'polydesk_settled' ORDER BY seq LIMIT 1")
    lines = []
    raw = _xp_map(desk).get("real_closed")
    for row in raw if isinstance(raw, list) else []:
        r = _xp_map(row)
        pnl = _num(r.get("pnl_usd"))
        if pnl is None or not isinstance(r.get("won"), bool):
            continue
        lines.append({"ts": _num(r.get("settled_at")), "won": r["won"],
                      "text": f"REAL · {'won' if r['won'] else 'lost'} {_signed(pnl)} · {r.get('question') or ''}"})
    return {"label": REAL_LABEL, "won": won, "lost": max(0, settled - won), "settled": settled,
            "since": _num(first[0][0]) if first else None, "order": order, "lines": lines}


def _shelf_results(trades: dict[str, Any], settings: Settings, money: Mapping[str, Any],
                   desk: Mapping[str, Any] | None) -> dict[str, Any]:
    """``trades.summary.result`` and ``.real.result`` (TROPHIES in the module docstring): what each shelf tier's money
    did since start, in the plain words' wording (real money said so only where it is real)."""
    summary = trades["summary"]
    summary["result"] = _change(_num(_xp_map(money.get("since_start")).get("usd")), real=settings.is_live)
    if summary["real"] is not None:
        real = _xp_map(_xp_map(desk).get("real")) if isinstance(desk, Mapping) else {}
        summary["real"]["result"] = _change(_num(real.get("since_start_usd")) or 0.0, real=True)
    return trades


def real_caps(settings: Settings, desk: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``risk_wall.real_caps`` (RISK WALL in the module docstring): the desk's real money against its hard limits, from
    the money card's real book and the settings; null unless the desk has a real book."""
    real = _xp_map(desk.get("real")) if isinstance(desk, Mapping) else {}
    if not real or not _real_book(real):
        return None
    return {"label": REAL_LABEL, "on": _xp_map(desk).get("mode") == "live",
            "open_usd": round(_num(real.get("at_risk_usd")) or 0.0, 2),
            "open_max_usd": float(settings.polydesk_live_max_open_usd),
            "day_loss_usd": round(max(0.0, -(_num(real.get("today_usd")) or 0.0)), 2),
            "day_max_usd": float(settings.polydesk_live_daily_loss_usd),
            "total_loss_usd": round(max(0.0, -(_num(real.get("since_start_usd")) or 0.0)), 2),
            "total_max_usd": float(settings.polydesk_live_total_loss_usd)}


def _desk_questions(settings: Settings) -> dict[str, str]:
    """The Polymarket desk's questions by market (its state file: open and kept closed rows), for the recap's real
    records (a receipt names the market only). Empty when the desk is off or its state cannot be read."""
    if not settings.polydesk_enabled:
        return {}
    try:
        st = load_state(state_path(settings))
    except (KeyError, TypeError, ValueError, AttributeError, OSError):
        return {}
    closed = st.get("closed")
    rows = [*_xp_map(st.get("positions")).values(), *(closed if isinstance(closed, list) else [])]
    out: dict[str, str] = {}
    for row in rows:
        r = _xp_map(row)
        slug, question = r.get("slug"), r.get("question")
        if isinstance(slug, str) and isinstance(question, str) and question and slug not in out:
            out[slug] = _clip(question, 80)
    return out


def recap_state(ledger: Any, settings: Settings, now: float, memory: dict[str, Any] | None = None,
                text: _Text | None = None, desk: Mapping[str, Any] | None = None,
                sol_usd: float | None = None) -> dict[str, Any]:
    """``recap`` (RECAP in the module docstring): the day's records (:func:`nightcrawler.recap.collect_recap` for this
    mode, with the money card's Polymarket block ``desk``), kept in ``memory`` for
    :data:`~nightcrawler.recap.RECAP_TTL_S` per day, zone and mode, worded on every call in the page's plain words with
    the page's own SOL price (``sol_usd``: a closed trade's dollar figure is ``trades.closed``'s). A failure to read
    them is logged and gives an empty recap: the rest of the page never depends on it."""
    mode = "live" if settings.is_live else "paper"
    live = settings.is_live
    try:
        key = (mode, settings.owner_tz, day_window(now, settings.owner_tz)[0])  # a new day is a new recap at once
        kept = memory.get("recap") if memory is not None else None
        if (isinstance(kept, dict) and kept.get("key") == key
                and 0 <= now - float(kept.get("at", -1e18)) < RECAP_TTL_S and isinstance(kept.get("raw"), dict)):
            raw: dict[str, Any] = kept["raw"]
        else:
            raw = collect_recap(ledger, now, tz=settings.owner_tz, mode=mode, exit_words=EXIT_WORDS, desk=desk,
                                questions=_desk_questions(settings))
            if memory is not None:
                memory["recap"] = {"key": key, "at": now, "raw": raw}
        return render_recap(raw, words=lambda member, line: plain_event(member, line, live=live),
                            text=text if text is not None else _Text(settings), sol_usd=sol_usd)
    except (LedgerError, sqlite3.Error, ArithmeticError, AttributeError, LookupError, OSError, TypeError,
            ValueError) as exc:  # (a bad row must never take the page down: the film then has nothing to play)
        log.warning("recap_failed error=%s", type(exc).__name__)
        return empty_recap(now, settings.owner_tz)


def _usage(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """``(rows, alerts)``: one row per provider; a budget that is used up also goes to the header. Until the
    call counters have saved anything (kv ``usage.providers``) a row says "not measured yet", never "0 calls"
    (the AI judge measures its own spending, so its row always counts)."""
    rows, alerts = [], []
    counted = state["usage"]["updated_at"] is not None
    for r in state["usage"]["providers"]:
        when = "today" if r["period"] == "day" else "this month"
        if not counted and r["id"] != "anthropic":
            rows.append({"label": r["label"], "pct": None, "level": None, "text": "not measured yet",
                         "measured": False})
        elif r["budget"]:
            if r["unit"] == "usd":
                used = f"${r['used']:.2f} of ${r['budget']:.2f} {when}"
            else:
                used = f"{int(r['used']):,} of {int(r['budget']):,} {r['unit']} {when}"
            rows.append({"label": r["label"], "pct": r["used_pct"], "level": r["level"], "text": used,
                         "measured": True})
            if r["level"] == "over":
                alerts.append({"level": "warn", "text": f"{r['label']} is over its "
                               f"{'daily' if r['period'] == 'day' else 'monthly'} budget ({r['used_pct']:.0f}%)."})
        else:
            calls = int(r["calls_today"])
            rows.append({"label": r["label"], "pct": None, "level": None,
                         "text": f"{calls:,} call{'' if calls == 1 else 's'} today", "measured": True})
    return rows, alerts


def _alerts(ledger: Any, state: dict[str, Any], now: float, withdrawal: dict[str, Any] | None = None,
            settings: Settings | None = None) -> list[dict[str, str]]:
    """Header banners from real trouble only, worst first. ``withdrawal``: :func:`nightcrawler.withdraw.page_view`
    (WITHDRAW_TO set, or the hold after a live withdrawal): its banner comes first and replaces the kill-switch
    banner the engine's forced sell-off (or hold) would show."""
    out = []
    if withdrawal is not None:
        out.append((withdrawal["level"], withdrawal["text"]))
    elif state["kill"] == "sell_all":
        out.append(("bad", "Kill switch is ON: the bot is selling everything and buying nothing."))
    elif state["kill"] == "stop":
        out.append(("bad", "Kill switch is ON: the bot buys nothing new (open trades are still looked after)."))
    unused = unused_wallet(settings, ledger) if settings is not None else None
    if unused is not None:
        out.append(("bad", f"The bot's own wallet {unused or '(address unknown)'} is not in use: BOT_WALLET_MODE is "
                           "not 'generated'. If it holds SOL, only the bot can move it: set BOT_WALLET_MODE=generated "
                           "(delete BOT_WALLET_SECRET), then take it back with WITHDRAW_TO."))
    if state["halted"]["halted"]:
        out.append(("bad", "Stopped buying: the money fell too far from its high. It stays stopped until you "
                           "reset it (RESET_HALT_TOKEN in Railway)."))
    status = state["engine"]["status"] or {}
    if status.get("drift"):
        out.append(("bad", "The wallet doesn't match the bot's own records: new buys are blocked until it's checked."))
    if ledger.get_kv("engine.safe_mode") or status.get("safe_mode"):
        out.append(("bad", "Safe mode: the settings are invalid, so the bot only sells. Fix the settings in Railway."))
    heartbeat = state["engine"]["heartbeat"]
    if heartbeat is None:
        out.append(("warn", "The bot has not started yet: nothing is running."))
    elif status.get("state") == "stopped":
        out.append(("bad", "The bot is stopped."))
    elif now - heartbeat > STALE_BANNER_S:
        out.append(("bad", f"The bot has not checked in for {duration_text(now - heartbeat)}: it may be down."))
    if status.get("unresolved_swaps"):
        out.append(("warn", "A trade's outcome is unknown: the bot is checking the wallet and pauses new buys."))
    out.sort(key=lambda a: a[0] != "bad")  # stable: worst first, otherwise in the order above
    return [{"level": level, "text": text} for level, text in out]


def _wallet(ledger: Any, settings: Settings, state: dict[str, Any], point: EquityPoint | None, now: float
            ) -> tuple[str | None, float | None, float | None]:
    """``(address, SOL, read at)`` of the bot wallet for checklist step 3 and the wallet card; SOL is None unless
    read in the last :data:`WALLET_MAX_AGE_S`. Live: the wallet's SOL in the last snapshot (not its total value,
    which counts the coins it holds). Paper: the engine's own reading, only while a bot wallet is set up; with
    the bot's own wallet its address is known from the start, and a reading of another wallet does not count."""
    if settings.is_live:
        address = state["wallet"]["address"]
        after = fresh_balance(saved_state(ledger), point.ts if point is not None else None)
        if after is not None and now - after[1] <= WALLET_MAX_AGE_S:  # read right after a withdrawal landed
            return address, after[0], after[1]
        if point is None or now - point.ts > WALLET_MAX_AGE_S:
            return address, None, None
        return address, point.sol_lamports / LAMPORTS_PER_SOL, point.ts
    saved = saved_balance(ledger) if wallet_configured(settings) else None
    own = ledger.get_kv(KV_GENERATED) if settings.bot_wallet_mode == "generated" else None
    if isinstance(own, str) and own and (saved is None or saved.address != own):
        return own, None, None
    if saved is None:
        return None, None, None
    if now - saved.checked_at > WALLET_MAX_AGE_S:
        return saved.address, None, None
    return saved.address, saved.sol_lamports / LAMPORTS_PER_SOL, saved.checked_at


def _wallet_card(settings: Settings, address: str | None, sol: float | None, read_at: float | None,
                 withdraw_state: dict[str, Any] | None) -> dict[str, Any]:
    """The bot wallet's deposit address (public), its SOL and how to fund it from Phantom."""
    own = settings.bot_wallet_mode == "generated"
    note = None
    if not address:
        note = ("No bot wallet yet. Set BOT_WALLET_MODE=generated in Railway: the bot makes its own wallet and shows "
                "its address here." if not (settings.is_live or wallet_configured(settings))
                else "The address shows here once the bot has started.")
    return {"address": address, "sol": sol, "checked_at": read_at, "own": own,
            "help": FUND_HELP if address else None, "keep_note": KEEP_NOTE if address and own else None,
            "paper_note": ("This is real SOL, even in paper mode: paper trades never spend it."
                           if address and not settings.is_live else None),
            "note": note, "last_withdrawal": last_withdrawal(withdraw_state)}


# =========================================================================== plain words (PLAIN)

_SIDE_WORDS = {"long": "YES", "short": "NO"}
_MONEY = r"\$(?P<usd>\d[\d,]*(?:\.\d+)?)"
#: (member, pattern, template): the event kinds a newcomer meets most, each in fixed plain words filled with the
#: event's own words and numbers. ``{kind}`` is what the Solana bot trades with; ``{side}`` YES or NO.
_EVENT_TEMPLATES: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (member, re.compile(pattern), template) for member, pattern, template in (
        ("predict", rf"Paper buy: (?P<q>.+) · (?P<side>long|short) at [\d.]+ · {_MONEY}.*",
         "practice bet (pretend money): ${usd} on {side} · {q}"),
        ("predict", rf"REAL buy: (?P<q>.+) · [\d.]+ contracts? at [\d.]+ \({_MONEY}.*",
         "real-money bet: ${usd} on YES · {q}"),
        ("predict", r"Settled: (?P<q>.+) · (?P<res>won|lost) [+-]?(?P<usd>[\d.]+) \$ \(paper\)",
         "a practice bet (pretend money) {res} ${usd} · {q}"),
        ("predict", r"Settled: (?P<q>.+) · (?P<res>won|lost) [+-]?(?P<usd>[\d.]+) \$ \(real\)",
         "a real-money bet {res} ${usd} · {q}"),
        ("predict", r"No fill at [\d.]+: (?P<q>.+) \(order cancelled\)",
         "a real-money order found no seller and was cancelled · {q}"),
        ("predict", r"Order not confirmed yet at [\d.]+: (?P<q>.+) \(counted as open money until the venue shows it\)",
         "a real-money order is waiting for Polymarket to confirm it · {q}"),
        ("predict", rf"REAL buy confirmed late by the venue: (?P<q>.+) · [\d.]+ contracts? at [\d.]+ \({_MONEY}.*",
         "Polymarket confirmed a real-money bet late: ${usd} · {q}"),
        ("predict", r"Refused a game whose prices do not add up: (?P<q>.+) \(YES bids add up to (?P<sum>[\d.]+)\)",
         "skipped a game whose prices did not add up (${sum} for a $1 prize): {q}"),
        ("predict", r"Refused a question whose prices do not add up: (?P<q>.+) \(YES bids add up to (?P<sum>[\d.]+)\)",
         "skipped a question whose prices did not add up (${sum} for a $1 prize): {q}"),
        ("predict", r"Order still unconfirmed after a day at [\d.]+: (?P<q>.+) \(no longer counted.*",
         "a real-money order was never confirmed by Polymarket and is no longer counted · {q}"),
        ("predict", r"Practice record for (?P<s>.+?) clears the risk manager's bar.*",  # (fits PLAIN_EVENT_MAX)
         "practice on {s} looks good; real money stays off until a second check and the owner say yes"),
        ("predict", r"Order rejected by the venue \([^)]*\): (?P<q>.+)", "Polymarket refused a real-money order · {q}"),
        ("predict", rf"REAL position found at the venue: (?P<q>.+) · [\d.]+ contracts? at [\d.]+ \({_MONEY}\)",
         "found a real-money bet already at Polymarket: ${usd} · {q}"),
        # the desk's own stops (polydesk's caps, the risk manager): what they mean for real money
        ("predict", r"Daily loss cap reached: no more real buys today\.",
         "hit today's loss limit: no more real-money bets until midnight UTC"),
        ("predict", r"Total loss cap reached: real trading stopped, back to paper\.",
         "hit the total loss limit: real money is off for good, practice only"),
        ("predict", r"Risk manager paused (?P<what>.+?): (?P<why>.+)",
         "the risk manager paused {what}: its record is losing ({why})"),
        ("predict", r"Paper book full .*", "the practice book is full: no new pretend bets until some finish"),
        # the no-lose check (practice only)
        ("predict", r"No-lose set found: (?P<q>.+): all (?P<n>\d+) answers for \$(?P<sum>[\d.]+) \(pays \$1\.00\)",
         "practice found a question whose {n} answers cost ${sum} together and pay $1 whatever happens: {q}"),
        ("predict", r"No-lose set paid: (?P<q>.+?): \$(?P<pay>[\d.]+) back for \$(?P<cost>[\d.]+) .*",
         "a practice no-lose set paid ${pay} back for ${cost} (pretend money): {q}"),
        ("predict", r"No-lose set BROKEN: (?P<q>.+?): paid \$(?P<pay>[\d.]+) for \$(?P<cost>[\d.]+) .*",
         "a practice no-lose set paid only ${pay} for ${cost} (pretend money): not no-lose after all · {q}"),
        # a candidate row only (teamroom._crawler: the coin, then its age, worth or feed); anything else as written
        ("crawler", r"(?P<coin>[^·]+?) · (?P<age>[\d.]+ (?:min|h) old)(?: · .*)?", "found a new coin: {coin} ({age})"),
        ("crawler", r"(?P<coin>[^·]+?) · (?:worth [^·]+|found on [^·]+)(?: · .*)?", "found a new coin: {coin}"),
        ("crawler", r"(?P<coin>[^\s·]+)", "found a new coin: {coin}"),
        ("cocoon", r"PASS (?P<coin>.+?) · .*", "{coin} passed the scam check"),
        ("cocoon", r"REJECT (?P<coin>.+?) · (?P<why>.+)", "threw out {coin}: {why}"),
        ("radar", r"FLAGGED (?P<coin>.+?) · (?P<why>.+)", "spotted danger on {coin}: {why}"),
        ("radar", r"CLEAR (?P<coin>.+?) · .*", "checked {coin} right before buying: all clear"),
        ("judge", r"YES \d+% · (?P<coin>.+?) · (?P<why>.+)", "the AI judge said yes to {coin}: {why}"),
        ("judge", r"NO \d+% · (?P<coin>.+?) · (?P<why>.+)", "the AI judge said no to {coin}: {why}"),
        ("strategy", r"DROP (?P<coin>.+?) · (?P<why>.+)", "stopped watching {coin}: {why}"),
        ("strategy", r"SETUP (?P<coin>.+?) · the drop and the bounce came · bought",
         "the buy signal came for {coin}: bought ({kind})"),
        ("strategy", r"SETUP (?P<coin>.+?) · stopped by (?P<who>[^:]+): (?P<why>.+)",
         "the buy signal came for {coin}, but {who} stopped it: {why}"),
        ("broker", r"BUY (?P<coin>.+?) for (?P<sol>[\d.]+) SOL .*", "bought {coin} for {sol} SOL ({kind})"),
        ("broker", r"SELL (?P<coin>.+?) for (?P<sol>[\d.]+) SOL .*", "sold {coin} for {sol} SOL ({kind})"),
        ("risk", r"REFUSED (?P<coin>.+?) · (?P<why>.+)", "refused to buy {coin}: {why}"),
        ("receipts", r"#(?P<n>\d+) (?P<what>.+?) · [0-9a-f]{8}", "sealed record #{n} in the tamper-proof log ({what})"),
    )
)


def _pretend_word(found: re.Match[str]) -> str:
    """The bot's own word "paper" (or "Paper", a sentence's first word) said as "pretend"; a ticker such as "PAPER"
    is a coin's name and stays as it is."""
    return "Pretend" if found.group(1) == "P" else "pretend"


#: The books' words in an event the templates leave as the bot wrote it: "(paper)" first, then a standalone "paper".
_BOOK_WORDS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"\(paper\)"), "(pretend money)"), (re.compile(r"\(real\)"), "(real money)"),
    (re.compile(r"\b([Pp])aper\b"), _pretend_word),
)


def plain_event(member: str, text: str, *, live: bool = False) -> str:
    """One team event in plain words (``plain.now``, ``plain.team[].latest``): the first fixed template of
    :data:`_EVENT_TEMPLATES` that matches the member's event, filled with the event's own words and numbers; any
    other event as the bot wrote it ("(paper)" said as "(pretend money)" and "paper" as "pretend"). ``live``: the
    Solana bot trades real money (its buys and sells then say "real money", else "pretend money"). Clipped to
    :data:`PLAIN_EVENT_MAX`."""
    kind = "real money" if live else "pretend money"
    for who, pattern, template in _EVENT_TEMPLATES:
        found = pattern.fullmatch(text) if who == member else None
        if found is not None:
            words = {key: (value or "").strip() for key, value in found.groupdict().items()}
            words["side"] = _SIDE_WORDS.get(words.get("side", ""), words.get("side", ""))
            return _clip(template.format(kind=kind, **words), PLAIN_EVENT_MAX)
    for pattern, book in _BOOK_WORDS:
        text = pattern.sub(book, text)
    return _clip(text, PLAIN_EVENT_MAX)


def _ago(seconds: float) -> str:
    return "just now" if seconds < 60 else f"{duration_text(seconds)} ago"


def _limit(value: float) -> str:
    """A cap in dollars, whole when it is whole: ``$10``, ``$2.50``."""
    return f"${value:,.0f}" if abs(value - round(value)) < 0.005 else f"${value:,.2f}"


def _change(value: float | None, *, real: bool) -> str:
    """A result since the start in words. A gain is worded "up $X since start (real money)" for real money, and only
    when the figure shows it; "pretend" money is said by the caller's label."""
    if value is None:
        return "no money check yet"
    cents = round(value, 2)
    if cents > 0:
        return f"up {_dollars(cents)} since start" + (" (real money)" if real else "")
    if cents < 0:
        return f"down {_dollars(cents)} since start"
    return "even since start"


def _money_word(live: bool) -> str:
    return "real money" if live else "pretend money"


def _real_figures(real: Mapping[str, Any], *, venue: bool = True) -> str:
    """The real book in words: the venue's cash, the money in open real bets, the result since start and the finished
    bets won (never one figure added to another). ``venue``: name the venue after the cash."""
    cash, held, n = _num(real.get("cash_usd")), _num(real.get("at_risk_usd")) or 0.0, _count(real.get("open")) or 0
    where = " at Polymarket" if venue else ""
    cash_part = f"{_dollars(cash)} cash{where}" if cash is not None else f"cash{where} not read yet"
    bets = "no open bets" if not n else f"{_dollars(held)} in {n} open bet{'' if n == 1 else 's'}"
    pending = _num(real.get("pending_usd")) or 0.0
    if round(pending, 2) > 0:  # orders the venue has not confirmed: real money too, never added to the bets
        bets += f", plus {_dollars(pending)} in orders Polymarket has not confirmed yet"
    settled, won = _count(real.get("settled_total")) or 0, _count(real.get("won_total")) or 0
    result = ("no bet has finished yet" if not settled else
              f"{_change(_num(real.get('since_start_usd')) or 0.0, real=True)}, {won} of {settled} finished bets won")
    return f"{cash_part} and {bets}; {result}"


def _real_paused(settings: Settings, desk: Mapping[str, Any], real: Mapping[str, Any]) -> tuple[str, str] | None:
    """``(kind, sentence)``: why the live desk sends no new real bet right now, from its own data, or None. ``risk``:
    the risk manager's pause (the paper record's stops real buys too); ``day``: the UTC day's loss cap; ``full``: the
    open-money cap already full at the rule's lowest price (``polydesk_theta``; unconfirmed orders count), which is
    waiting, not a pause; ``room``: if every open bet lost, a loss stop would be passed by one more bet (the stops
    count money still at risk), so it waits for some to finish; with nothing open and only the day's room gone, that
    is the day's stop (``day``)."""
    guard = _xp_map(desk.get("guard"))
    for book, record in ((guard, "the rule's practice record"), (_xp_map(guard.get("real")), "its real-money record")):
        if book.get("paused"):
            since = f" since {book['since']}" if book.get("since") else ""
            return "risk", f"Paused by the risk manager{since}: {record} was losing money, so it places no new real bets."
    today = _num(real.get("today_usd")) or 0.0
    daily = float(settings.polydesk_live_daily_loss_usd)
    if today <= -daily:
        return "day", (f"Stopped for today: it lost {_dollars(today)} today and the daily limit is {_limit(daily)}. "
                       "It can bet again after midnight UTC.")
    pending = _num(real.get("pending_usd")) or 0.0
    held, cap = (_num(real.get("at_risk_usd")) or 0.0) + pending, float(settings.polydesk_live_max_open_usd)
    bet = float(settings.polydesk_theta) * float(settings.polydesk_live_contracts)
    if held + bet > cap + 1e-9:
        return "full", (f"Waiting: {_dollars(held)} is already in open bets and the most allowed at once is "
                        f"{_limit(cap)}; it bets again when one finishes.")
    room = _num(real.get("stop_room_usd"))
    if room is None or room >= bet:
        return None
    total = real.get("stop_room_limit") == "total"
    limit = _limit(float(settings.polydesk_live_total_loss_usd) if total else daily)
    if held > 0:
        what = f"the total would pass the {limit} limit" if total else f"today would pass the {limit} limit"
        return "room", f"Waiting: if every open bet lost, {what}, so it waits for some to finish."
    if not total:
        return "day", (f"Stopped for today: one more lost bet could pass the {limit} daily limit. It can bet again "
                       "after midnight UTC.")
    return "room", f"Stopped: one more lost bet could pass the {limit} total loss limit, so it places no new real bets."


#: How the page names a sport of :data:`nightcrawler.polydesk.SPORT_HISTORY` for a newcomer.
_SPORT_WORDS = {"hockey": "ice hockey", "mma/boxing": "boxing/MMA", "american football": "American football"}


def _sports_words(sports: list[str]) -> str:
    names = [_SPORT_WORDS.get(s, s) for s in sports]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _sports_line() -> str:
    """``plain.real.sports_line``: why real money skips sports, from lab 4's history verdicts
    (:data:`nightcrawler.polydesk.SPORT_HISTORY`, :data:`~nightcrawler.polydesk.SPORT_HISTORY_POOLED`) and the sports
    real money may bet (:data:`~nightcrawler.polydesk.REAL_SPORTS_ALLOWED`: none; any ever allowed is named)."""
    allowed = [s for s in SPORT_HISTORY if s in REAL_SPORTS_ALLOWED]

    def judged(verdict: str) -> list[str]:
        return [s for s, (v, _) in SPORT_HISTORY.items() if v == verdict and s not in REAL_SPORTS_ALLOWED]

    pooled = SPORT_HISTORY_POOLED
    history = (f"in history ({int(pooled['buys']):,} past bets like these, {int(pooled['lost'])} lost: "
               f"{100 * pooled['loss_rate']:.1f}% against the {100 * pooled['implied']:.1f}% the prices said) no "
               f"{'other ' if allowed else ''}sport proved it pays")
    head = (f"Real money on sports only for {_sports_words(allowed)}; {history}." if allowed
            else f"No real money on sports: {history}.")
    parts = []
    if judged("proven loser"):
        words = _sports_words(judged("proven loser"))
        parts.append(f"{words[:1].upper()}{words[1:]} favourites lost more often than their prices said")
    if judged("no history"):
        little = judged("too little history")
        parts.append(f"{_sports_words(judged('no history'))} have no history"
                     + (f", {_sports_words(little)} too little" if little else ""))
    if judged("unproven"):
        parts.append(f"{_sports_words(judged('unproven'))} are unproven")
    body = "; ".join(parts)
    return f"{head} {body[:1].upper()}{body[1:]}. Practice bets keep watching them." if body else \
        f"{head} Practice bets keep watching them."


def _skips_line(desk: Mapping[str, Any], *, live: bool) -> str:
    """``plain.real.skips_line``: what the desk skipped today and why, from its own counts (``money.polymarket.skips``),
    the parts that are not zero; the sports part only while real money is on."""
    counts = _xp_map(_xp_map(desk.get("skips")).get("counts"))

    def n(reason: str) -> int:
        return _count(counts.get(reason)) or 0

    parts = []
    if live and n("sports_no_real"):
        parts.append(f"practised {n('sports_no_real')} sports bet{'' if n('sports_no_real') == 1 else 's'} instead "
                     "of betting real money")
    if n("incoherent_game"):
        one = n("incoherent_game") == 1
        parts.append(f"refused {n('incoherent_game')} game{'' if one else 's'} whose prices did not add up")
    if n("incoherent_question"):
        one = n("incoherent_question") == 1
        parts.append(f"refused {n('incoherent_question')} question{'' if one else 's'} whose answers' prices did not "
                     "add up")
    if n("never_traded"):
        one = n("never_traded") == 1
        parts.append(f"skipped {n('never_traded')} market{'' if one else 's'} that had never traded near the price")
    if not parts:
        return "Nothing skipped yet today."
    said = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + ("," if len(parts) > 2 else "") + " and " + parts[-1]
    return f"Today it {said}."


def _arbs_line(desk: Mapping[str, Any]) -> str | None:
    """``plain.real.arbs_line``: the no-lose check in one sentence, from the desk's own counts
    (``money.polymarket.arbs``), only on a UTC day it found one (else None). Always "practice": no real money."""
    arbs = _xp_map(desk.get("arbs"))

    def n(key: str) -> int:
        return _count(arbs.get(key)) or 0

    seen, bought, checked, there, broken = (n("today_seen"), n("today_bought"), n("today_checked"),
                                            n("today_still_there"), n("broken"))
    if not seen:
        return None
    one = seen == 1
    found = f"found {seen} question{'' if one else 's'} whose every answer cost under $1 together today, fees included"
    parts = [found]
    if bought == seen:
        parts.append("practice bought " + ("the set" if one else "both sets" if seen == 2 else f"all {seen} sets"))
    elif bought:
        parts.append(f"practice bought {bought} of the sets")
    else:
        parts.append("practice bought none (an answer was already held)")
    if checked:
        parts.append(f"{there if there else 'none'} {'was' if there <= 1 else 'were'} still there at the next look")
    if broken:
        sets = "1 practice set paid back less than it" if broken == 1 else f"{broken} practice sets paid back less than they"
        parts.append(f"{sets} cost, so that kind of question is not no-lose")
    return f"No-lose check (practice): {'; '.join(parts)}."


def _desk_silent(settings: Settings, desk: Mapping[str, Any] | None) -> bool:
    """The owner asked for live (``POLYDESK_MODE=live``) but the desk has said nothing yet: no state that says live, no
    reason of its own why not, no round finished (a missing or unreadable state file reads as an empty paper one).
    The page then cannot know whether real money is on, and says so instead of "pretend"."""
    if not (settings.polydesk_enabled and settings.polydesk_mode == "live"):
        return False
    if desk is None:
        return True
    return desk.get("mode") != "live" and not desk.get("status") and desk.get("as_of") is None


def _plain_real(settings: Settings, money: Mapping[str, Any], desk: Mapping[str, Any] | None, *,
                passed: bool) -> dict[str, Any]:
    """``plain.real``: real money in plain words (PLAIN in the module docstring)."""
    raw = desk.get("real") if desk is not None else None
    real: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    desk_live = desk is not None and desk.get("mode") == "live"
    silent = not desk_live and _desk_silent(settings, desk)
    sentences = []
    if desk_live:
        sentences.append(f"Real money: {_real_figures(real)}.")
    elif silent:
        sentences.append("Real money: no report yet from Voss's Polymarket bets, so this page cannot say if any is "
                         "at stake there.")
    solana = _num(_xp_map(money.get("since_start")).get("usd")) if settings.is_live else None
    if settings.is_live:
        sentences.append(f"The Solana bot trades real money: {_change(solana, real=True)}.")
    if not sentences:
        reason = desk.get("status") if desk is not None and settings.polydesk_mode == "live" else None
        line = "Real money is off" + (f": {str(reason).rstrip('.')}" if reason else "")
        if real:
            line += f". Still at Polymarket: {_real_figures(real, venue=False)}."
        else:
            line += "." if reason else ": everything is practice with pretend money."
        sentences.append(line)
    paused = _real_paused(settings, desk, real) if desk is not None and desk_live else None
    settled = _count(real.get("settled_total")) or 0
    if desk is not None and settled:  # the desk's real bets: the result once one has finished
        result: str | None = _change(_num(real.get("since_start_usd")) or 0.0, real=True)
    elif settings.is_live and solana is not None:
        result = _change(solana, real=True)
    else:
        result = None
    cap = float(settings.polydesk_live_contracts)
    per = "one contract (under $1)" if cap == 1 else f"{cap:g} contracts (under {_limit(cap)})"
    limits = (f"Hard limits: {per} per bet, at most {_limit(settings.polydesk_live_max_open_usd)} in bets at once, "
              f"stops for the day after losing {_limit(settings.polydesk_live_daily_loss_usd)}, stops for good after "
              f"losing {_limit(settings.polydesk_live_total_loss_usd)}.")
    # how the rule bets, from its settings: YES only, practice and real alike (polydesk rule 2026-10-10a); a contract
    # pays $1, so a win is at most the rest of the dollar and a loss the whole price
    theta = round(float(settings.polydesk_theta) * 100)
    how = (f"How it bets: it buys YES at {theta}¢ or more on questions that look "
           f"almost decided. A right answer pays $1, so a win makes at most {100 - theta}¢ a contract and a loss "
           "costs the whole price.")
    if RULE_LAB_PASSED:
        verdict = VERDICT_PASSED if desk_live else VERDICT_PASSED_OFF
    else:
        verdict = VERDICT_NO_EDGE if desk_live else VERDICT_NO_EDGE_OFF
    return {
        "label": REAL_LABEL, "on": desk_live or settings.is_live, "reported": not silent,
        "paused": paused[1] if paused else None,
        "paused_kind": paused[0] if paused else None,
        "at_risk_usd": (_num(real.get("at_risk_usd")) or 0.0) if real or desk_live else None,
        "open_bets": (_count(real.get("open")) or 0) if real or desk_live else None,
        "cash_usd": _num(real.get("cash_usd")),
        "result": result,
        "line": " ".join(sentences),
        "how": how if desk is not None else None,
        "limits": limits if desk is not None else None,
        "verdict": verdict if desk is not None else None,
        "research": RESEARCH_LINE if not (RULE_LAB_PASSED or passed) else None,
        # why real money skips sports (lab 4's history), and what the desk skipped today and why (its own counts)
        "sports_line": _sports_line() if desk is not None else None,
        "skips_line": _skips_line(desk, live=desk_live) if desk is not None else None,
        # the no-lose check (practice only), on a day it found a question whose every answer cost under $1
        "arbs_line": _arbs_line(desk) if desk is not None else None,
    }


def _plain_pretend(settings: Settings, money: Mapping[str, Any], desk: Mapping[str, Any] | None,
                   trend: Mapping[str, Any] | None, now: float) -> dict[str, Any]:
    """``plain.pretend``: each practice book in its own clause, always "pretend", never added together; the
    Polymarket desk's paper book since start like the others (today's change beside it)."""
    parts = []
    if not settings.is_live:
        since = _num(_xp_map(money.get("since_start")).get("usd"))
        parts.append("the Solana bot has no money check yet" if since is None
                     else f"the Solana bot is {_change(since, real=False)}")
    if desk is not None:
        paper = _xp_map(desk.get("paper"))
        since = _num(paper.get("since_start_usd"))
        if desk.get("as_of") is None:
            book = "Polymarket practice bets have not finished a round yet"
        elif since is None:
            book = "Polymarket practice bets have no result yet"
        else:
            book = f"Polymarket practice bets are {_change(since, real=False)}"
            today = round(_num(paper.get("today_usd")) or 0.0, 2)
            if today:
                book += f" ({_signed(today)} today)"
        if _xp_map(desk.get("guard")).get("paused"):
            book += " (paused by the risk manager)"
        parts.append(book)
    if trend is not None:
        started = trend.get("started")
        if trend.get("as_of") is not None:
            parts.append(f"the trend desk is {_change(_num(trend.get('since_start_usd')), real=False)}")
        elif started == utc_day(now):
            parts.append("the trend desk starts tonight (midnight UTC)")
        else:
            parts.append("the trend desk has not booked its first day yet")
    body = ("; ".join(parts) if parts else "nothing is practising right now") + "."
    return {"label": PRETEND_LABEL, "line": f"{PRETEND_LABEL}: {body}", "body": body[:1].upper() + body[1:]}


def _plain_headline(settings: Settings, desk: Mapping[str, Any] | None, real: Mapping[str, Any]) -> str:
    """One sentence for the top of both pages (at most :data:`PLAIN_HEADLINE_MAX` characters: two lines on a phone).
    Real money is said to be off only when no real bet is open either."""
    desk_live = desk is not None and desk.get("mode") == "live"
    cap = float(settings.polydesk_live_max_open_usd)
    bets = "Voss's small Polymarket bets" if cap <= PLAIN_SMALL_DESK_USD else "Voss's Polymarket bets"
    if desk_live and settings.is_live:
        return "Real money is on for the Solana bot and Voss's Polymarket bets; the rest is pretend money."
    if settings.is_live and not real.get("reported", True):
        return "Real money is on for the Solana bot; no report yet from Voss's Polymarket bets."
    if settings.is_live:
        return "Real money is on for the Solana bot; everything else is practice with pretend money."
    kind = real.get("paused_kind")
    if desk_live and kind == "risk":
        return "Real money is on for Voss's Polymarket bets but paused now; the rest is pretend money."
    if desk_live and kind == "day":
        return "Real money is on for Voss's Polymarket bets but stopped for today; the rest is pretend."
    if desk_live and kind == "full":
        return f"Real money is on for Voss's Polymarket bets, at its {_limit(cap)} limit; the rest is pretend."
    if desk_live and kind == "room":
        if real.get("open_bets") or (desk is not None and _xp_map(desk.get("real")).get("pending")):
            return "Real money is on for Voss's Polymarket bets, waiting on open bets; the rest is pretend."
        return "Real money is on for Voss's Polymarket bets, at its loss limit; the rest is pretend."
    if desk_live:
        return f"Real money is on only for {bets}; the rest is pretend money."
    if not real.get("reported", True):
        return "Real money: no report yet from Voss's Polymarket bets; the rest is pretend money."
    n = real.get("open_bets") or 0
    if n > 0:  # off for new bets, but real money is still out in open bets at the venue
        held = f"{_dollars(real.get('at_risk_usd') or 0.0)} is still in {n} open bet{'' if n == 1 else 's'}"
        line = f"Real money is off for new bets, but {held}; the rest is pretend."
        return line if len(line) <= PLAIN_HEADLINE_MAX else f"Real money is off for new bets, but {held}."
    return "No real money is being bet right now: everything is practice with pretend money."


def _cast_members(key: str) -> list[str]:
    """The bot members a character of :data:`nightcrawler.office3d.CAST3D` plays."""
    raw = CAST3D[key]["members"]
    return [str(m) for m in raw] if isinstance(raw, list) else []


def _plain_team(members: list[dict[str, Any]], now: float, *, live: bool, desk_live: bool
                ) -> tuple[list[dict[str, Any]], list[str], dict[str, dict[str, Any]]]:
    """``(plain.team, plain.now, plain.said)``: the six characters with their job, status word and latest event; the
    team's freshest events in the last :data:`PLAIN_NOW_WINDOW_S` (the receipts' own log left out: it records every
    step); and each member's newest event in plain words (the 3D world's speech bubbles). ``live``: the Solana bot
    trades real money; ``desk_live``: the Polymarket desk does (each job says which money it handles)."""
    actor_of = {m: key for key in CAST3D for m in _cast_members(key)}
    by_id = {m["id"]: m for m in members}
    events = []
    for m in members:
        for ev in m.get("events") or []:
            ts, text = _num(ev.get("ts")), ev.get("text")
            if ts is not None and ts <= now + FUTURE_SKEW_S and isinstance(text, str) and text.strip():
                events.append((ts, m["id"], text.strip()))
    events.sort(key=lambda e: -e[0])  # stable: a tie keeps the members' order (the risk desk before the Polymarket desk)
    lines: list[str] = []
    seen: set[str] = set()
    for ts, mid, text in events:
        if len(lines) >= PLAIN_NOW_MAX or ts < now - PLAIN_NOW_WINDOW_S:
            break
        if mid == "receipts" or text in seen or mid not in actor_of:
            continue
        seen.add(text)
        name = str(CAST3D[actor_of[mid]]["name"])
        lines.append(f"{name}: {plain_event(mid, text, live=live)} · {_ago(max(0.0, now - ts))}")
    said: dict[str, dict[str, Any]] = {}
    for ts, mid, text in events:  # newest first: each member's first one is its newest
        if mid not in said:
            said[mid] = {"ts": ts, "text": plain_event(mid, text, live=live)}
    team = []
    for key, template in PLAIN_JOBS.items():
        spec = CAST3D[key]
        ids = _cast_members(key)
        job = template.format(desk=_money_word(desk_live), solana=_money_word(live))
        statuses = {by_id[m]["status"] for m in ids if m in by_id}
        word = next((PLAIN_STATUS[s] for s in PLAIN_STATUS if s in statuses), "idle")
        latest = next(((ts, mid, text) for ts, mid, text in events if mid in ids), None)
        team.append({"id": key, "name": str(spec["name"]), "job": job, "plain_role": f"{spec['name']} {job}",
                     "status_word": word, "members": ids,
                     "latest": said[latest[1]]["text"] if latest else None,
                     "latest_ts": latest[0] if latest else None,
                     "latest_ago": _ago(max(0.0, now - latest[0])) if latest else None})
    return team, lines, said


def plain_ticker(members: list[dict[str, Any]], now: float, *, live: bool) -> list[dict[str, Any]]:
    """``plain.ticker`` (TICKER in the module docstring): the team's last :data:`PLAIN_TICKER_MAX` events of the last
    :data:`PLAIN_TICKER_WINDOW_S`, newest first, in plain words (:func:`plain_event`), each with the character who made
    it and the event's own tone; the receipts' own log left out and the same words once. ``live``: the Solana bot
    trades real money."""
    actor_of = {m: key for key in CAST3D for m in _cast_members(key)}
    events = []
    for m in members:
        mid = m.get("id")
        if mid == "receipts" or mid not in actor_of:
            continue
        for ev in m.get("events") or []:
            ts, text = _num(ev.get("ts")), ev.get("text")
            if ts is None or not isinstance(text, str) or not text.strip():
                continue
            if ts > now + FUTURE_SKEW_S or ts < now - PLAIN_TICKER_WINDOW_S:
                continue
            tone = ev.get("tone") if ev.get("tone") in ("good", "bad") else "neutral"
            events.append((ts, str(mid), text.strip(), tone))
    events.sort(key=lambda e: -e[0])  # stable: a tie keeps the members' order
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ts, mid, text, tone in events:
        words = plain_event(mid, text, live=live)
        if words in seen:
            continue
        seen.add(words)
        key = actor_of[mid]
        out.append({"ts": ts, "who": key, "name": str(CAST3D[key]["name"]), "text": words, "tone": tone})
        if len(out) >= PLAIN_TICKER_MAX:
            break
    return out


def plain_finished(closed: list[dict[str, Any]] | None, settled: Any, *, live: bool) -> list[dict[str, Any]]:
    """``plain.finished`` (FINISHED in the module docstring): the newest :data:`PLAIN_FINISHED_MAX` things that really
    finished, newest first: the Solana bot's closed trades (``closed``: the page's ``trades.closed`` rows; real money
    only while the bot runs live, ``live``) and the Polymarket desk's settled real-money bets (``settled``: its
    ``money.polymarket.settled_real``, read from the desk's whole event log; None while the desk is off). Nothing
    else: a practice bet that settles is not in it."""
    items: list[dict[str, Any]] = []
    for row in closed or []:
        ts, coin, result = _num(row.get("closed_at")), row.get("coin"), row.get("result")
        if ts is None or not isinstance(coin, str) or not coin or result not in ("won", "lost", "even"):
            continue
        pnl = _num(row.get("pnl_usd"))
        items.append({"id": f"trade|{coin}|{ts:.3f}", "ts": ts, "who": "jet", "what": coin, "result": result,
                      "usd": round(abs(pnl), 2) if pnl is not None else None, "real": live,
                      "money": "real money" if live else "pretend"})
    for ev in settled if isinstance(settled, list) else []:
        if not isinstance(ev, Mapping):
            continue
        ts, text = _num(ev.get("ts")), ev.get("text")
        found = _REAL_SETTLED.fullmatch(text.strip()) if isinstance(text, str) and ts is not None else None
        if found is None or ts is None:
            continue
        question = found.group("q").strip()
        items.append({"id": f"bet|{ts:.3f}|{question}", "ts": ts, "who": "voss", "what": question,
                      "result": found.group("res"), "usd": round(abs(float(found.group("pnl"))), 2), "real": True,
                      "money": "real money"})
    items.sort(key=lambda i: -i["ts"])
    return items[:PLAIN_FINISHED_MAX]


def plain_words(settings: Settings, money: Mapping[str, Any], members: list[dict[str, Any]], now: float, *,
                passed: bool = False, closed: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """``/api/page.plain`` (PLAIN in the module docstring): the screen in plain words, from this page's own data only.
    ``money`` is the money card (its ``polymarket`` and ``trend`` blocks are the two desks), ``members`` the team rows
    (their status and events), ``passed`` whether the Coach's champion passed its locked test, ``closed`` the page's
    closed trades (``trades.closed``, for ``finished``). Never raises on a missing figure: an unknown one is said so."""
    desk = money.get("polymarket")
    desk = desk if isinstance(desk, Mapping) and isinstance(desk.get("paper"), Mapping) else None
    trend = money.get("trend")
    trend = trend if isinstance(trend, Mapping) else None
    real = _plain_real(settings, money, desk, passed=passed)
    desk_live = desk is not None and desk.get("mode") == "live"
    team, lines, said = _plain_team(members, now, live=settings.is_live, desk_live=desk_live)
    return {
        "about": PLAIN_ABOUT,
        "headline": _plain_headline(settings, desk, real),
        "real": real,
        "pretend": _plain_pretend(settings, money, desk, trend, now),
        "now": lines,
        "team": team,
        "said": said,
        "jobs": {mid: PLAIN_MEMBER_JOBS[mid] for mid, _, _ in MEMBERS if mid in PLAIN_MEMBER_JOBS},
        "glossary": [{"word": word, "means": means} for word, means in GLOSSARY],
        # the 3D world's ticker and replay banner (TICKER and FINISHED in the module docstring)
        "ticker": plain_ticker(members, now, live=settings.is_live),
        "finished": plain_finished(closed, desk.get("settled_real") if desk is not None else None,
                                   live=settings.is_live),
    }


# =========================================================================== assembly


def build_page_state(ledger: Any, settings: Settings, now: float, engine_status: dict[str, Any] | None = None,
                     *, verify_cache: dict[str, Any] | None = None, memory: dict[str, Any] | None = None,
                     deploy: dict[str, str | None] | None = None) -> dict[str, Any]:
    """Assemble ``/api/page`` (schema in the module docstring). Same arguments as
    :func:`nightcrawler.teamroom.build_team_state`; ``memory`` also caches the learning card."""
    text = _Text(settings)
    state = build_state(ledger, settings, now, verify_cache)
    team = build_team_state(ledger, settings, now, engine_status, verify_cache=verify_cache, memory=memory,
                            deploy=deploy, state=state)
    card = learning_card(settings, now, ledger, memory)
    members = _members(team, card, now)
    counts = {"working": 0, "idle": 0, "waiting": 0, "blocked": 0}
    for m in members:
        if m["status"] in counts:  # a member that is not built yet is not part of the team's count
            counts[m["status"]] += 1
    usage, usage_alerts = _usage(state)
    withdraw_state = saved_state(ledger)
    withdrawal = page_view(settings, withdraw_state, now, live_hold(ledger))
    alerts = _alerts(ledger, state, now, withdrawal, settings)
    point = _latest_point(ledger, "live" if settings.is_live else "paper")
    address, wallet_sol, wallet_read_at = _wallet(ledger, settings, state, point, now)
    desk = polymarket_desk(settings, now)  # the Polymarket desk's books, apart from the SOL wallet (never summed)
    trend = trend_desk(settings, now)  # the trend desk's paper book, apart from everything else (never summed)
    money = _money(settings, state["equity"], point, _withdrawn(ledger, settings, point, now), desk, trend)
    for m in members:  # Rook's risk wall: the desk's real money against its hard limits beside the panel's numbers
        if m["id"] == "risk" and isinstance(m.get("risk_wall"), dict):
            m["risk_wall"]["real_caps"] = real_caps(settings, desk)
    receipts = state["receipts"]
    head = receipts["head_hash"]
    trades = _shelf_results(_trades(ledger, settings, state, text, desk), settings, money, desk)
    out = {
        "version": __version__,
        "generated_at": now,
        "mode": state["mode"],
        "refresh_s": REFRESH_S,
        "alerts": alerts + usage_alerts,
        # the screen in plain words, from the figures below only (never one kind of money added to another)
        "plain": plain_words(settings, money, members, now, passed=card["champion_passed_locked_test"],
                             closed=trades["closed"]),
        "money": money,
        # the town: what running the bot costs against what the desks made (same clock as the judge's total)
        "town": town_ledger(settings, money, state.get("judge"), now, _run_started(ledger, state)),
        "team": {"counts": counts, "members": members},
        "trades": trades,
        # yesterday in the owner's time zone, from the ledger and its receipts only (the 3D world's recap film)
        "recap": recap_state(ledger, settings, now, memory, text, desk, state["equity"]["sol_usd"]),
        "learning": {"source": card["source"], "state": card["state"], "headline": card["headline"],
                     "variants": card["variants"], "data": card["data"],
                     "rule": LEARNING_RULE if card["source"] == "card" and card["can_stop_trading"] else None},
        # read-only: the report cards never feed the checklist below or the banners
        "experience": experience_card(settings, now, card, memory),
        # never "Ready" while a banner says the bot is stopped, silent or in trouble (budget banners aside)
        "ready": readiness(settings, card, wallet_address=address, wallet_sol=wallet_sol, stopped=bool(alerts),
                           now=now),
        "wallet": _wallet_card(settings, address, wallet_sol, wallet_read_at, withdraw_state),
        "withdraw": withdrawal,
        "receipts": {"count": receipts["count"], "verified": receipts["verified"],
                     "first_bad_seq": receipts["first_bad_seq"], "head": head, "head_short": f"{head[:8]}…{head[-8:]}"},
        "usage": usage,
        "research": research_state(),  # what the labs found: a fixed copy of the record (RESEARCH above)
        "about": {"version": __version__, "uptime_s": team["engine"]["uptime_s"],
                  "commit": (deploy or {}).get("commit"), "started_at": team["engine"]["started_at"]},
    }
    # the town's goal (GOAL): display only, from the figures above; a failure shows no goal at all, never a zero
    try:
        live_days, today_pnls = goal_books(ledger, settings, now)
        out["town"]["goal"], out["plain"]["goal"] = town_goal_block(settings, out, now, live_days=live_days,
                                                                     today_pnls=today_pnls)
    except Exception as exc:  # noqa: BLE001 - the goal must never take the page down
        log.warning("town_goal_failed error=%s", type(exc).__name__)
        out["town"]["goal"] = out["plain"]["goal"] = None
    clean: dict[str, Any] = scrub(out, text.secrets)
    return clean
