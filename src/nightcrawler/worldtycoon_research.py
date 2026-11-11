"""Read-only browser summaries of each practice desk and observation service.

Each row keeps its producer's timestamp and accounting scope. A daily candle
close is not a worker heartbeat, and no practice result becomes real profit.
"""

TYCOON_RESEARCH = r"""
  function tycoonResearch(d, now, pageCurrent) {
    const money = tycoonObject(d.money), speed = tycoonObject(money.speeddesk);
    const trend = tycoonObject(money.trend), coins = tycoonObject(trend.in_market);
    const coinNames = ["BTC", "ETH", "SOL"];
    const coinCount = coinNames.every(function (key) { return typeof coins[key] === "boolean"; })
      ? coinNames.filter(function (key) { return coins[key]; }).length : null;
    const rows = [
      { key: "speed", name: "Bitcoin lab", scope: "PRACTICE", raw: speed, limit: 60,
        count: tycoonObject(speed.today).day === tycoonUtcDate(now) ? tycoonCount(tycoonObject(speed.today).fills) : null,
        countLabel: "practice fills today (UTC)", status: "Bitcoin practice book; both venues" },
      { key: "watcher", name: "Bot research", scope: "READ ONLY", raw: tycoonObject(d.skipwatch), limit: 60,
        count: tycoonCount(tycoonObject(d.skipwatch).wallet_fills), countLabel: "public fills recorded",
        status: "Recording public trades; no orders" },
      { key: "weather", name: "Weather lab", scope: "READ ONLY", raw: tycoonObject(d.weatherwatch), limit: 120,
        count: tycoonCount(tycoonObject(d.weatherwatch).active_watches), countLabel: "markets being watched",
        status: "Recording observations and prices; no orders" },
      // The producer books once daily, allowing one hour for the next UTC close.
      { key: "trend", name: "Crypto trend lab", scope: "PRACTICE", raw: trend, limit: 90000,
        count: coinCount, countLabel: "practice coin positions", timeLabel: "Daily close (UTC)",
        status: "Daily Bitcoin, Ethereum and Solana practice book" },
      { key: "arena", name: "Strategy arena", scope: "PRACTICE", raw: tycoonObject(money.arena), limit: 180,
        count: tycoonCount(tycoonObject(money.arena).population), countLabel: "practice strategies",
        status: "Strategies competing with practice money" },
      { key: "marco", name: "Marco’s NFL picks", scope: "PRACTICE", raw: tycoonObject(money.marco), limit: 600,
        count: tycoonCount(tycoonObject(tycoonObject(money.marco).record).picks),
        countLabel: "practice picks settled", status: "NFL picks tracked with practice money" },
      { key: "nhl", name: "Hockey picks", scope: "PRACTICE", raw: tycoonObject(money.nhl), limit: 600,
        count: tycoonCount(tycoonObject(tycoonObject(money.nhl).record).picks),
        countLabel: "practice picks settled", status: "NHL picks tracked with practice money" },
    ];
    return rows.map(function (r) {
      const stamp = tycoonStamp(r.raw.as_of, now), age = tycoonAge(stamp, now);
      const wrongMode = r.scope === "PRACTICE" && r.raw.mode !== undefined && r.raw.mode !== "paper";
      const current = pageCurrent && now !== null && stamp !== null && r.raw.stale !== true
        && !tycoonOld(age, r.limit) && !wrongMode;
      const problem = tycoonText(r.raw.problem);
      const status = wrongMode ? "Practice report has an unexpected mode; figures unavailable"
        : !current ? "Waiting for a current report" : problem || tycoonText(r.raw.status) || r.status;
      return { key: r.key, name: r.name, scope: r.scope, current: current,
        state: !current ? "unknown" : problem ? "attention" : "observing", status: status,
        asOf: stamp, age: age, count: stamp !== null && !wrongMode ? r.count : null,
        countLabel: r.countLabel, timeLabel: r.timeLabel || "Report checked", realOrders: false };
    });
  }
"""
