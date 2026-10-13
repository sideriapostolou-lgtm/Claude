"""Pure, read-only browser projection of the two real desks' saved records."""

TYCOON_CONNECTIONS = r"""
  function tycoonProfitReason(raw, current, name) {
    const day = tycoonObject(raw), code = tycoonText(day.reason), prefix = name + " profit today is unverified: ";
    const reasons = { day_book_mismatch: "saved result totals do not match the daily book.",
      unfinished_poll: "the last account update did not finish.", missing_book: "some saved result records are missing.",
      missing_snapshot: "no completed account report is available.", snapshot_before_day: "the latest account report predates midnight Pacific.",
      invalid_result: "a saved result could not be validated.", invalid_day_book: "a saved daily total could not be validated.",
      desk_reconciliation_problem: "the desk reports an accounting problem.",
      timezone_unavailable: "the Pacific calendar day could not be determined." };
    if (reasons[code]) return prefix + reasons[code];
    if (day.status === "incomplete") return prefix + "the saved results are incomplete or do not reconcile.";
    if (!current) return prefix + (day.status === "ok" ? "the report is missing, old or for a different Pacific day."
      : "a complete Pacific-day report is unavailable.");
    return "";
  }
  function tycoonPacific(raw, now, limit, sourceCurrent) {
    const day = tycoonObject(raw), start = tycoonStamp(day.start, now), end = tycoonNumber(day.end);
    const at = tycoonStamp(day.as_of, now), age = tycoonAge(at, now);
    let date = "";
    if (now !== null && now > 0 && now < 8640000000000) {
      try {
        const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles",
          year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(now * 1000));
        const part = function (type) { const p = parts.find(function (item) { return item.type === type; }); return p ? p.value : ""; };
        date = part("year") + "-" + part("month") + "-" + part("day");
      } catch (_) { /* A missing Pacific calendar never falls back to the UTC day. */ }
    }
    const matches = now !== null && start !== null && end !== null && start <= now && now < end
      && day.tz === "America/Los_Angeles" && date !== "" && day.date === date && at !== null && at >= start;
    const known = matches && day.status === "ok" && tycoonNumber(day.pnl_usd) !== null;
    return { value: known ? tycoonNumber(day.pnl_usd) : null, date: matches ? tycoonText(day.date) : "",
      asOf: at, age: age, current: known && sourceCurrent && !tycoonOld(age, limit),
      status: known ? "ok" : tycoonText(day.status) || "unavailable", reasonCode: tycoonText(day.reason) };
  }
  function tycoonConnections(d, now, pageCurrent) {
    const raw = tycoonObject(tycoonObject(d.money).connections), venues = {}, activity = [];
    const available = raw.version === 1;
    ["polymarket_us", "kalshi"].forEach(function (key) {
      const row = available ? tycoonObject(raw[key]) : {}, limit = key === "kalshi" ? 60 : 600;
      const asOf = tycoonStamp(row.as_of, now), age = tycoonAge(asOf, now);
      const reportFresh = pageCurrent && now !== null && asOf !== null && row.stale === false && !tycoonOld(age, limit);
      const current = reportFresh && row.status === "ok";
      const name = key === "kalshi" ? "Kalshi" : "Polymarket";
      const positions = (Array.isArray(row.positions) ? row.positions : []).slice(0, 50).map(function (p) {
        p = tycoonObject(p);
        return { id: tycoonText(p.id), title: tycoonText(p.title) || tycoonText(p.market),
          side: tycoonText(p.side).toUpperCase(), scope: p.scope === "bot" ? "bot" : p.scope === "owner" ? "owner" : "unknown",
          quantity: tycoonCost(p.quantity), price: tycoonCost(p.price), cost: tycoonCost(p.cost_usd),
          fee: tycoonCost(p.fee_usd), feeBasis: tycoonText(p.fee_source) || tycoonText(p.fee_basis), openedAt: tycoonStamp(p.opened_at, now),
          status: tycoonText(p.status), statusNote: tycoonText(p.status_note), endAt: tycoonNumber(p.end_at),
          finalOutcome: ["YES", "NO"].includes(p.final_outcome) ? p.final_outcome : null,
          mixedAccountActivity: p.mixed_account_activity === true, currentPositionVerified: p.current_position_verified === true };
      });
      const orders = (Array.isArray(row.orders) ? row.orders : []).slice(0, 50).map(function (o) {
        o = tycoonObject(o);
        return { id: tycoonText(o.id), title: tycoonText(o.title) || tycoonText(o.market),
          side: tycoonText(o.side).toUpperCase(), status: (tycoonText(o.status) || "Unconfirmed")
            + (o.cancel_requested === true && o.reservation_active === true ? " · cancellation pending" : ""),
          quantity: tycoonCost(o.quantity), filled: tycoonCost(o.filled_quantity), remaining: tycoonCost(o.remaining_quantity),
          reserved: tycoonCost(o.reserved_usd), asOf: tycoonStamp(o.as_of, now), lock: o.lock === true };
      });
      const issues = (Array.isArray(row.issues) ? row.issues : []).filter(function (v) { return typeof v === "string"; }).slice(0, 10);
      const day = tycoonPacific(row.today_pacific, now, limit, current);
      day.reason = tycoonProfitReason(row.today_pacific, day.current, name);
      if (row.status === "incomplete" && day.status === "ok") day.reason = name + " profit today is unverified: saved money records need review.";
      venues[key] = { name: name, asOf: asOf, age: age, current: current, reportFresh: reportFresh, status: tycoonText(row.status),
        sourceNote: tycoonText(row.source_note), positionsBasis: tycoonText(row.positions_basis),
        positions: positions, orders: orders, issues: issues, truncated: tycoonObject(row.truncated),
        day: day };
      (Array.isArray(row.events) ? row.events : []).slice(0, 50).forEach(function (e) {
        e = tycoonObject(e);
        const ts = tycoonStamp(e.ts, now), sourceAt = tycoonStamp(e.source_at, now), id = tycoonText(e.id);
        if (e.real !== true || e.venue !== key || !["bot", "owner"].includes(e.scope) || !id || ts === null
            || !["order", "fill", "cancel", "reject", "settlement"].includes(e.type) || !tycoonText(e.text)) return;
        const words = tycoonText(e.text), eventText = words.startsWith(name + " · ") ? words.slice(name.length + 3)
          : words.startsWith(name + " ") ? words.slice(name.length + 1) : words;
        activity.push({ id: id, venue: key, kind: e.type, ts: ts, age: tycoonAge(ts, now), real: true,
          scope: e.scope, text: name + (e.scope === "owner" ? " · Your activity" : "") + " · " + eventText,
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
      kalshiActivity: activity.filter(function (e) { return e.venue === "kalshi"; }),
      today: complete ? sum : null, todayCurrent: complete, date: complete ? pm.date : "" };
  }
  function tycoonBusinessCrew(s) {
    const k = s.business.venues.kalshi, kalshi = s.accounts.kalshi;
    const fresh = kalshi.current && k.reportFresh;
    const latest = s.activity.find(function (e) { return e.scope === "bot" && e.current; });
    const kText = "Kalshi: " + kalshi.stateText + ".";
    const roles = {
      voss: { job: "Kalshi Bitcoin", detail: "Shows the Kalshi Bitcoin desk’s reported state. Polymarket stays separate in Money.",
        doing: kText + (kalshi.waiting || kalshi.reason ? " " + (kalshi.waiting || kalshi.reason) : "") },
      rook: { job: "Kalshi safeguards", detail: "Reports Kalshi’s limits and stops. The trading desk enforces them.",
        doing: kText + (kalshi.integrityNote ? " " + kalshi.integrityNote : "")
          + (kalshi.totalHalted ? " " + kalshi.stopNote : "")
          + (k.status === "incomplete" ? " Saved Kalshi money records need review." : "")
          + (!k.day.current ? " " + k.day.reason : "")
          + (kalshi.cleanupPending ? " Kalshi cancellation is still pending." : "") },
      jet: { job: "Kalshi orders", detail: "Shows Kalshi order receipts. The trading desk places its own orders.",
        doing: (kalshi.current ? "Kalshi: " : "Last Kalshi report: ")
          + (kalshi.orders === null ? "order count unreported" : kalshi.orders + " open orders")
          + ". A submitted order is not a fill or profit." },
      mote: { job: "Kalshi records", detail: "Shows Kalshi fills, actual fees and settled bot results. Practice never counts as profit.",
        doing: latest ? latest.text : "Waiting for recorded Kalshi activity." },
    };
    return s.crew.map(function (c) {
      const role = roles[c.key];
      if (!role) return Object.assign({}, c, { background: true,
        job: c.practice === true ? "Practice " + (c.key === "pip" ? "scouting" : "checks") : "Background " + c.job.toLowerCase(),
        jobDetail: c.jobDetail + " This work stays behind the scenes and does not grow the Kalshi town." });
      const attention = kalshi.cleanupPending || kalshi.integrityError || kalshi.integrityReset || kalshi.totalHalted
        || k.status === "incomplete";
      return Object.assign({}, c, { job: role.job, jobDetail: role.detail, doing: role.doing, recordedWork: role.doing,
        statusReason: role.doing, background: false,
        status: !fresh ? "unknown" : c.key === "rook" && attention ? "stuck"
          : latest && latest.age <= 60 ? "working" : "waiting",
        practice: null, age: latest ? latest.age : null });
    });
  }
"""
