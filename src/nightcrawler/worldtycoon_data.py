"""Pure browser adapter for the world's phone HUD; display only, with no new money sources."""

from nightcrawler.worldtycoon_connections import TYCOON_CONNECTIONS
from nightcrawler.worldtycoon_research import TYCOON_RESEARCH

TYCOON_DATA = TYCOON_CONNECTIONS + TYCOON_RESEARCH + r"""
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
  function tycoonUtcDate(now) {
    // Convert the caller's timestamp only; this adapter never reads a clock.
    if (now === null || now <= 0 || now > 8640000000000) return "";
    return new Date(now * 1000).toISOString().slice(0, 10);
  }
  function tycoonGrowth(s) {
    const thresholds = [0.01, 0.25, 1, 5, 10];
    if (s.business && s.business.available) {
      const qualified = s.business.todayCurrent, pnl = s.business.today;
      return { qualified: qualified, level: qualified ? thresholds.filter(function (p) { return pnl >= p - 1e-9; }).length : null,
        pnl_usd: pnl, thresholds: thresholds, label: "Both bots’ recorded profit since midnight PT", date: s.business.date,
        reason: qualified ? null : "Waiting for complete, fresh Pacific-day results from both desks" };
    }
    const qualified = s.todayStatus === "ok" && s.today !== null && s.updated !== null && s.asOf !== null
      && s.on !== null && !s.pageStale && !s.deskStale && !s.todayStale;
    // These are today's decorative gardens, not account capital or purchased buildings.
    // A loss, a correction or Pacific midnight can remove an earned decoration.
    const level = qualified ? thresholds.filter(function (p) { return s.today >= p - 1e-9; }).length : null;
    return { qualified: qualified, level: level, pnl_usd: s.today, thresholds: thresholds,
      label: "Polymarket bot profit since midnight PT", date: s.todayDate,
      reason: qualified ? null : s.pageStale || s.deskStale || s.todayStale ? "Waiting for a fresh profit report"
        : "Waiting for a complete Pacific-day bot profit report" };
  }
  function tycoonKalshi(d, now, pageCurrent) {
    const raw = tycoonObject(tycoonObject(tycoonObject(d.money).speeddesk).kalshi_live);
    const asOf = tycoonStamp(raw.as_of, now), cashAt = tycoonStamp(raw.cash_at, now);
    const age = tycoonAge(asOf, now), cashAge = tycoonAge(cashAt, now);
    const present = Object.keys(raw).length > 0, mode = raw.mode === "live" || raw.mode === "paper" ? raw.mode : null;
    const stale = present && (!pageCurrent || raw.stale === true || asOf === null || tycoonOld(age, 60));
    const current = present && pageCurrent && now !== null && asOf !== null && !stale;
    const active = current && mode === "live" && raw.active === true && raw.authenticated === true
      && raw.real_orders_available === true;
    const hasExposure = raw.has_real_exposure === true;
    const state = !present ? "unknown" : stale ? "stale" : active ? "live" : hasExposure ? "exposure"
      : mode === "paper" ? "practice" : "unknown";
    const today = tycoonObject(raw.today), total = tycoonObject(raw.total), caps = tycoonObject(raw.caps), date = tycoonUtcDate(now);
    const dayCurrent = date !== "" && today.day === date;
    const cashStale = cashAt === null || tycoonOld(cashAge, 60) || stale;
    return { name: "Kalshi", state: state, active: active, practice: state === "practice", mode: mode,
      stateText: state === "live" ? "Real-money trading is enabled" : state === "exposure" ? "Real bets remain open"
        : state === "practice" ? "Practice only; no new real orders" : state === "stale" ? "Waiting for a fresh Kalshi report"
        : "No current Kalshi report",
      reason: tycoonText(raw.reason), asOf: asOf, age: age, stale: stale, current: current,
      cash: cashAt !== null ? tycoonCost(raw.cash_usd) : null, cashAt: cashAt, cashAge: cashAge, cashStale: cashStale,
      today: dayCurrent ? tycoonNumber(today.pnl_usd) : null, todayDate: dayCurrent ? date : "",
      todayNote: "Bot profit since midnight UTC", todayStale: stale || !dayCurrent,
      total: tycoonNumber(total.pnl_usd), fees: dayCurrent ? tycoonCost(today.fees_usd) : null,
      locked: dayCurrent ? tycoonNumber(today.locked_usd) : null,
      directional: dayCurrent ? tycoonNumber(today.directional_usd) : null,
      hasExposure: hasExposure, exposure: tycoonCost(raw.at_risk_usd), positions: tycoonCount(raw.positions),
      orders: tycoonCount(raw.open_orders), reserved: tycoonCost(raw.reserved_usd),
      cleanupPending: raw.cleanup_pending === true,
      totalHalted: raw.total_halted === true,
      limits: { window: tycoonCost(caps.window_usd), open: tycoonCost(caps.open_usd),
        day: tycoonCost(caps.day_stop_usd), total: tycoonCost(caps.total_stop_usd) },
      note: "Separate Kalshi account. Cash is not profit. Its UTC result does not count toward Pacific-day gardens." };
  }
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
    const day = tycoonObject(real.today_pacific), start = tycoonStamp(day.start, now), end = tycoonNumber(day.end);
    const dayMatches = now !== null && day.tz === "America/Los_Angeles" && start !== null && end !== null
      && start <= now && now < end;
    const todayAsOf = dayMatches ? tycoonStamp(day.as_of, now) : null;
    const todayReady = dayMatches && todayAsOf !== null && todayAsOf >= start && day.status === "ok"
      && tycoonNumber(day.pnl_usd) !== null;
    const todayAge = tycoonAge(todayAsOf, now), todayStale = tycoonOld(todayAge, TYCOON_DESK_STALE_S);
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
    const risk = members.find(function (m) { return m && m.id === "risk"; });
    const caps = tycoonObject(tycoonObject(risk && risk.risk_wall).real_caps);
    const rows = desk && Array.isArray(desk.positions) ? desk.positions : [], positions = [];
    for (let i = 0; i < rows.length; i++) {
      const row = tycoonObject(rows[i]);
      if (row.live !== true) continue;
      const p = tycoonNumber(row.p_in);
      positions.push({ question: tycoonText(row.question), side: row.side === "long" ? "YES" : row.side === "short" ? "NO" : "Unknown",
        price: p !== null && p >= 0 && p <= 1 ? p : null, scope: "account", owner: "unknown" });
    }
    const cash = tycoonNumber(real.cash_usd), fallbackCash = tycoonNumber(plainReal.cash_usd);
    const summary = { cash: cash !== null ? cash : fallbackCash,
      today: todayReady ? tycoonNumber(day.pnl_usd) : null,
      todayAsOf: todayAsOf, todayAge: todayAge, todayStale: todayStale,
      todayDate: dayMatches ? tycoonText(day.date) : "",
      todayStatus: todayReady ? "ok" : dayMatches && day.status === "incomplete" ? "incomplete" : "unavailable",
      count: venueAsOf !== null ? tycoonCount(real.venue_open) : null,
      value: venueAsOf !== null ? tycoonCost(real.value_usd) : null,
      recorded: { count: asOf !== null ? tycoonCount(real.open) : null,
        cost: asOf !== null ? tycoonCost(real.at_risk_usd) : null },
      reportedCash: cashAsOf !== null ? tycoonNumber(real.cash_reported_usd) : null,
      buyingPower: cashAsOf !== null ? tycoonNumber(real.buying_power_usd) : null,
      on: on, state: state, pauseKind: pauseKind, deskStatus: deskStatus,
      stateText: state === "stale" ? "Waiting for a fresh update" : state === "unknown" ? "No current desk report"
        : state === "off" ? deskStatus || "No new bot bets" : state === "paused" ? pauseText : "Real-money desk is on",
      updated: updated, asOf: asOf, cashAsOf: cashAsOf, venueAsOf: venueAsOf,
      pageAge: pageAge, deskAge: deskAge, cashAge: cashAge, venueAge: venueAge,
      stale: stale, pageStale: pageStale, deskStale: deskStale, cashStale: cashStale, venueStale: venueStale,
      labels: { cash: "Available cash", cashNote: "Polymarket account", cashDetail: "Shared with your own bets",
        today: "Bot today", todayNote: "Since midnight PT", todayDetail: "Bot profit booked since midnight Pacific; excludes your own bets",
        bets: "Account bets", betsNote: "Includes your own bets", betsDetail: "Open markets and their value reported by Polymarket" },
      event: tycoonLatest(d, now), crew: tycoonCrew(d, now, now !== null && updated !== null && !pageStale,
        now !== null && asOf !== null && !deskStale), positions: positions,
      pending: { count: asOf !== null ? tycoonCount(real.pending) : null, held: asOf !== null ? tycoonCost(real.pending_usd) : null },
      limits: { open: tycoonCost(caps.open_max_usd), day: tycoonCost(caps.day_max_usd), total: tycoonCost(caps.total_max_usd),
        room: tycoonCost(real.stop_room_usd) },
      positionsNote: "Recorded positions, not the current venue book. App sales can leave these records behind; ownership is not supplied.",
      eventNote: "Latest recorded real event; historical settlements may later be corrected." };
    const pageCurrent = now !== null && updated !== null && !pageStale;
    summary.accounts = { kalshi: tycoonKalshi(d, now, pageCurrent) };
    summary.business = tycoonConnections(d, now, pageCurrent);
    summary.activity = summary.business.activity;
    summary.activitySources = { polymarket_us: summary.business.venues.polymarket_us.current,
      kalshi: summary.business.venues.kalshi.current };
    summary.accounts.kalshi.todayPacific = summary.business.venues.kalshi.day;
    if (summary.business.available) {
      summary.event = summary.activity.length ? summary.activity[0] : null;
      summary.eventNote = "Latest recorded real activity, with its venue and original time. Orders and fills are not profit.";
    }
    summary.crew = tycoonBusinessCrew(summary);
    summary.growth = tycoonGrowth(summary);
    summary.research = tycoonResearch(d, now, pageCurrent);
    return summary;
  }
  // <<< tycoon data
"""
