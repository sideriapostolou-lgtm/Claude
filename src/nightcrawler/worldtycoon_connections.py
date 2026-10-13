"""Pure, read-only browser projection of the two real desks' saved records."""

TYCOON_CONNECTIONS = r"""
  function tycoonPacific(raw, now, limit, sourceCurrent) {
    const day = tycoonObject(raw), start = tycoonStamp(day.start, now), end = tycoonNumber(day.end);
    const at = tycoonStamp(day.as_of, now), age = tycoonAge(at, now);
    const matches = now !== null && start !== null && end !== null && start <= now && now < end
      && day.tz === "America/Los_Angeles" && at !== null && at >= start;
    const known = matches && day.status === "ok" && tycoonNumber(day.pnl_usd) !== null;
    return { value: known ? tycoonNumber(day.pnl_usd) : null, date: matches ? tycoonText(day.date) : "",
      asOf: at, age: age, current: known && sourceCurrent && !tycoonOld(age, limit),
      status: known ? "ok" : tycoonText(day.status) || "unavailable" };
  }
  function tycoonConnections(d, now, pageCurrent) {
    const raw = tycoonObject(tycoonObject(d.money).connections), venues = {}, activity = [];
    const available = raw.version === 1;
    ["polymarket_us", "kalshi"].forEach(function (key) {
      const row = available ? tycoonObject(raw[key]) : {}, limit = key === "kalshi" ? 60 : 600;
      const asOf = tycoonStamp(row.as_of, now), age = tycoonAge(asOf, now);
      const current = pageCurrent && now !== null && asOf !== null && row.status === "ok"
        && row.stale === false && !tycoonOld(age, limit);
      const name = key === "kalshi" ? "Kalshi" : "Polymarket";
      const positions = (Array.isArray(row.positions) ? row.positions : []).slice(0, 50).map(function (p) {
        p = tycoonObject(p);
        return { id: tycoonText(p.id), title: tycoonText(p.title) || tycoonText(p.market),
          side: tycoonText(p.side).toUpperCase(), scope: p.scope === "bot" ? "bot" : p.scope === "owner" ? "owner" : "unknown",
          quantity: tycoonCost(p.quantity), price: tycoonCost(p.price), cost: tycoonCost(p.cost_usd),
          fee: tycoonCost(p.fee_usd), feeBasis: tycoonText(p.fee_source) || tycoonText(p.fee_basis), openedAt: tycoonStamp(p.opened_at, now) };
      });
      const orders = (Array.isArray(row.orders) ? row.orders : []).slice(0, 50).map(function (o) {
        o = tycoonObject(o);
        return { id: tycoonText(o.id), title: tycoonText(o.title) || tycoonText(o.market),
          side: tycoonText(o.side).toUpperCase(), status: (tycoonText(o.status) || "Unconfirmed")
            + (o.cancel_requested === true && o.reservation_active === true ? " · cancellation pending" : ""),
          quantity: tycoonCost(o.quantity), filled: tycoonCost(o.filled_quantity), remaining: tycoonCost(o.remaining_quantity),
          reserved: tycoonCost(o.reserved_usd), asOf: tycoonStamp(o.as_of, now) };
      });
      const issues = (Array.isArray(row.issues) ? row.issues : []).filter(function (v) { return typeof v === "string"; }).slice(0, 10);
      venues[key] = { name: name, asOf: asOf, age: age, current: current,
        sourceNote: tycoonText(row.source_note), positionsBasis: tycoonText(row.positions_basis),
        positions: positions, orders: orders, issues: issues, truncated: tycoonObject(row.truncated),
        day: tycoonPacific(row.today_pacific, now, limit, current) };
      (Array.isArray(row.events) ? row.events : []).slice(0, 50).forEach(function (e) {
        e = tycoonObject(e);
        const ts = tycoonStamp(e.ts, now), sourceAt = tycoonStamp(e.source_at, now), id = tycoonText(e.id);
        if (e.real !== true || e.venue !== key || !["bot", "owner"].includes(e.scope) || !id || ts === null
            || !["order", "fill", "cancel", "reject", "settlement"].includes(e.type) || !tycoonText(e.text)) return;
        activity.push({ id: id, venue: key, kind: e.type, ts: ts, age: tycoonAge(ts, now), real: true,
          scope: e.scope, text: name + (e.scope === "owner" ? " · Your activity" : "") + " · " + tycoonText(e.text),
          usd: e.type === "settlement" ? tycoonNumber(e.pnl_usd) : null, fee: tycoonCost(e.fee_usd), feeBasis: tycoonText(e.fee_source),
          timeSource: tycoonText(e.time_source), sourceAt: sourceAt,
          current: current && e.qualified === true && sourceAt !== null && !tycoonOld(tycoonAge(sourceAt, now), limit) });
      });
    });
    activity.sort(function (a, b) { return b.ts - a.ts || a.id.localeCompare(b.id); });
    const pm = venues.polymarket_us.day, k = venues.kalshi.day;
    const sum = pm.value !== null && k.value !== null ? tycoonNumber(pm.value + k.value) : null;
    const complete = available && pm.current && k.current && pm.date !== "" && pm.date === k.date && sum !== null;
    return { available: available, venues: venues, activity: activity.slice(0, 60),
      today: complete ? sum : null, todayCurrent: complete, date: complete ? pm.date : "" };
  }
  function tycoonBusinessCrew(s) {
    if (!s.business.available) return s.crew;
    const pm = s.business.venues.polymarket_us, k = s.business.venues.kalshi;
    const kalshi = s.accounts.kalshi, venues = [pm, k], fresh = venues.some(function (v) { return v.current; });
    const latest = s.activity.find(function (e) { return e.scope === "bot" && e.current; });
    const pmText = "Polymarket: " + s.stateText + ".", kText = "Kalshi: " + kalshi.stateText + ".";
    const roles = {
      voss: { job: "Bitcoin desks", detail: "Monitors Polymarket and the separate Kalshi Bitcoin desk.",
        doing: pmText + " " + kText },
      rook: { job: "Money safeguards", detail: "Reports each desk’s own limits and stops. The safeguards run in the trading desks.",
        doing: pmText + " " + kText + (kalshi.cleanupPending ? " Kalshi cancellation is still pending." : "") },
      jet: { job: "Order status", detail: "Shows real order receipts from both venues. Each trading desk places its own orders.",
        doing: "Polymarket: " + (s.pending.count === null ? "unreported" : s.pending.count + " unconfirmed orders")
          + ". Kalshi: " + (kalshi.orders === null ? "unreported" : kalshi.orders + " open orders")
          + ". A submitted order is not a fill or profit." },
      mote: { job: "Money records", detail: "Keeps the venue records separate: orders, fills, fees and settled results.",
        doing: latest ? latest.text : "Waiting for recorded real-money activity." },
    };
    return s.crew.map(function (c) {
      const role = roles[c.key]; if (!role) return c;
      const attention = kalshi.cleanupPending || s.state === "paused";
      return Object.assign({}, c, { job: role.job, jobDetail: role.detail, doing: role.doing, recordedWork: role.doing,
        status: !fresh ? "unknown" : c.key === "rook" && attention ? "stuck"
          : latest && latest.age <= 60 ? "working" : "waiting",
        practice: null, age: latest ? latest.age : null });
    });
  }
"""
