"""Pure browser adapter for the world's phone HUD; display only, with no new money sources."""

TYCOON_DATA = r"""
  // >>> tycoon data (pure)
  // These are separate books: cash and open positions belong to the shared account;
  // today's realized result belongs to the bot. Missing data never becomes zero.
  const TYCOON_PAGE_STALE_S = 60, TYCOON_DESK_STALE_S = 600;
  function tycoonObject(v) { return v && typeof v === "object" && !Array.isArray(v) ? v : {}; }
  function tycoonNumber(v) { return typeof v === "number" && isFinite(v) ? v : null; }
  function tycoonCount(v) { return tycoonNumber(v) !== null && v >= 0 && Math.floor(v) === v ? v : null; }
  function tycoonCost(v) { return tycoonNumber(v) !== null && v >= 0 ? v : null; }
  function tycoonText(v) { return typeof v === "string" ? v.trim() : ""; }
  function tycoonStamp(v, now) { return tycoonNumber(v) !== null && v > 0 && (now === null || v <= now + 60) ? v : null; }
  function tycoonAge(ts, now) { return ts !== null && now !== null ? Math.max(0, now - ts) : null; }
  function tycoonOld(age, limit) { return age !== null && age > limit; }
  function tycoonDollars(v) { return "$" + Math.abs(v).toFixed(2); }
  function tycoonLatest(d, now) {
    const plain = tycoonObject(d.plain), items = [], finished = Array.isArray(plain.finished) ? plain.finished : [];
    for (let i = 0; i < finished.length; i++) {
      const f = tycoonObject(finished[i]), ts = tycoonStamp(f.ts, now), what = tycoonText(f.what);
      if (f.real !== true || f.money !== "real money" || ts === null || !what
          || (f.who !== "voss" && f.who !== "jet") || !["won", "lost", "even"].includes(f.result)) continue;
      const usd = tycoonNumber(f.usd), result = f.result === "even" ? "Finished even" : f.result === "won" ? "Won" : "Lost";
      items.push({ id: tycoonText(f.id) || "result|" + ts + "|" + what, who: f.who, kind: "settlement",
        text: result + (usd !== null && f.result !== "even" ? " " + tycoonDollars(usd) : "") + " · " + what,
        ts: ts, age: tycoonAge(ts, now) });
    }
    items.sort(function (a, b) { return b.ts - a.ts; });
    return items.length ? items[0] : null;
  }
  function tycoonCrew(d, now, pageCurrent, deskCurrent) {
    const plain = tycoonObject(d.plain), team = Array.isArray(plain.team) ? plain.team : [];
    const members = Array.isArray(tycoonObject(d.team).members) ? d.team.members : [];
    const primary = { voss: "predict", rook: "risk", pip: "crawler", nyx: "cocoon", jet: "broker", mote: "receipts" };
    const grouped = { nyx: ["cocoon", "radar", "strategy"], mote: ["receipts", "coach"] };
    const statusWords = { blocked: "stuck", working: "working", waiting: "waiting", idle: "idle" };
    const statusOrder = ["blocked", "working", "waiting", "idle"];
    const jobs = { voss: "Trading", rook: "Risk checks", pip: "Finding coins", nyx: "Coin checks", jet: "Orders", mote: "Records" };
    const out = [], seen = {};
    for (let i = 0; i < team.length; i++) {
      const t = tycoonObject(team[i]), key = t.id;
      if (!Object.prototype.hasOwnProperty.call(primary, key) || seen[key]) continue;
      seen[key] = true;
      const ids = grouped[key] || [primary[key]];
      const candidates = members.filter(function (row) { return row && ids.includes(row.id); });
      // One character may play several bot roles. Use the member responsible for
      // the displayed status; Voss's Trading station specifically follows predict.
      candidates.sort(function (a, b) {
        const ai = statusOrder.indexOf(a.status), bi = statusOrder.indexOf(b.status);
        return (ai < 0 ? 4 : ai) - (bi < 0 ? 4 : bi)
          || (tycoonStamp(b.last_activity, now) || 0) - (tycoonStamp(a.last_activity, now) || 0);
      });
      const m = candidates[0] || {}, job = tycoonText(t.job);
      const status = statusWords[m.status] || (["working", "waiting", "idle", "stuck"].includes(t.status_word) ? t.status_word : "unknown");
      const ts = tycoonStamp(candidates.length ? m.last_activity : t.latest_ts, now);
      const stale = !pageCurrent || (key === "voss" && !deskCurrent);
      // "doing" is the member's recorded status description, never a repeated
      // old event presented as a new task. The last event stays in the event feed.
      const statusReason = tycoonText(m.why), recordedWork = tycoonText(m.doing);
      const doing = statusReason || recordedWork;
      out.push({ key: key, name: tycoonText(t.name) || key, job: jobs[key], jobDetail: job,
        status: stale ? "unknown" : status, doing: doing ? (stale ? "Last report: " : "") + doing : "No work reported yet.",
        statusReason: statusReason, recordedWork: recordedWork,
        age: tycoonAge(ts, now),
        practice: /\b(?:pretend|paper|practice)\b/i.test(job) ? true : /\breal money\b/i.test(job) ? false : null });
    }
    return out;
  }
  function tycoonSummary(value, nowSeconds) {
    const d = tycoonObject(value), money = tycoonObject(d.money), pm = tycoonObject(money.polymarket);
    const real = tycoonObject(pm.real), plainReal = tycoonObject(tycoonObject(d.plain).real);
    const now = tycoonNumber(nowSeconds), updated = tycoonStamp(d.generated_at, now), asOf = tycoonStamp(pm.as_of, now);
    const cashAsOf = tycoonStamp(real.cash_at, now), venueAsOf = tycoonStamp(real.venue_at, now);
    const pageAge = tycoonAge(updated, now), deskAge = tycoonAge(asOf, now);
    const cashAge = tycoonAge(cashAsOf, now), venueAge = tycoonAge(venueAsOf, now);
    const pageStale = tycoonOld(pageAge, TYCOON_PAGE_STALE_S), deskStale = tycoonOld(deskAge, TYCOON_DESK_STALE_S);
    const cashStale = tycoonOld(cashAge, TYCOON_DESK_STALE_S), venueStale = tycoonOld(venueAge, TYCOON_DESK_STALE_S);
    const on = pm.mode === "live" ? true : pm.mode === "paper" ? false : null;
    // The desk's own status explains why real buys stopped. The page's inferred
    // full/room messages mix account open cost with bot-only caps, so cannot
    // establish whether the bot has capacity. Keep only risk/day evidence.
    const deskStatus = tycoonText(pm.status), guard = tycoonObject(pm.guard);
    const guardPaused = guard.paused === true || tycoonObject(guard.real).paused === true;
    const trustedKind = ["risk", "day"].includes(plainReal.paused_kind) ? plainReal.paused_kind : null;
    const pauseKind = on !== true ? null : guardPaused ? "risk" : trustedKind || (deskStatus ? "reported" : null);
    const paused = on === true && pauseKind !== null;
    const pauseText = deskStatus || (trustedKind === pauseKind ? tycoonText(plainReal.paused) : "")
      || (pauseKind === "risk" ? "Risk manager paused new real bets." : "New real bets paused.");
    const stale = pageStale || deskStale;
    const state = stale ? "stale" : now === null || updated === null || asOf === null || on === null ? "unknown"
      : on === false ? "off" : paused ? "paused" : "on";
    const members = Array.isArray(tycoonObject(d.team).members) ? d.team.members : [];
    const desk = members.find(function (m) { return m && m.id === "predict"; });
    const rows = desk && Array.isArray(desk.positions) ? desk.positions : [], positions = [];
    for (let i = 0; i < rows.length; i++) {
      const row = tycoonObject(rows[i]);
      if (row.live !== true) continue;
      const p = tycoonNumber(row.p_in);
      positions.push({ question: tycoonText(row.question), side: row.side === "long" ? "YES" : row.side === "short" ? "NO" : "Unknown",
        price: p !== null && p >= 0 && p <= 1 ? p : null, scope: "account", owner: "unknown" });
    }
    const cash = tycoonNumber(real.cash_usd), fallbackCash = tycoonNumber(plainReal.cash_usd);
    return { cash: cash !== null ? cash : fallbackCash,
      today: asOf !== null ? tycoonNumber(real.today_usd) : null,
      count: asOf !== null ? tycoonCount(real.open) : null,
      held: asOf !== null ? tycoonCost(real.at_risk_usd) : null,
      on: on, state: state, pauseKind: pauseKind, deskStatus: deskStatus,
      stateText: state === "stale" ? "Waiting for a fresh update" : state === "unknown" ? "No current desk report"
        : state === "off" ? deskStatus || "No new bot bets" : state === "paused" ? pauseText : "Real-money desk is on",
      updated: updated, asOf: asOf, cashAsOf: cashAsOf, venueAsOf: venueAsOf,
      pageAge: pageAge, deskAge: deskAge, cashAge: cashAge, venueAge: venueAge,
      stale: stale, pageStale: pageStale, deskStale: deskStale, cashStale: cashStale, venueStale: venueStale,
      labels: { cash: "Available cash", cashNote: "Polymarket account", cashDetail: "Shared with your own bets",
        today: "Bot today", todayNote: "Realized · UTC", todayDetail: "Bot settlements and cash-outs booked today; excludes your own bets",
        bets: "Account bets", betsNote: "Includes your own bets", betsDetail: "Recorded cost in open real bets, excluding unconfirmed orders" },
      event: tycoonLatest(d, now), crew: tycoonCrew(d, now, now !== null && updated !== null && !pageStale,
        now !== null && asOf !== null && !deskStale), positions: positions,
      pending: { count: asOf !== null ? tycoonCount(real.pending) : null, held: asOf !== null ? tycoonCost(real.pending_usd) : null },
      positionsNote: "Account positions; ownership is not supplied. The list may be incomplete.",
      eventNote: "Latest recorded real event; historical settlements may later be corrected." };
  }
  // <<< tycoon data
"""
