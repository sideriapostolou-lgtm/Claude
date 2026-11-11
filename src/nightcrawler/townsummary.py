"""Small read-only town fallback, using the same money projection as the 3D view.

The response is static and contains no account data or credentials. Its one script
reads the existing authenticated page API; it has no trading or configuration path.
"""

from __future__ import annotations

import base64
import hashlib

from nightcrawler.worldtycoon_data import TYCOON_DATA

__all__ = ["SUMMARY_CSP", "render_summary_html"]

_STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #203846; background: #eaf4fa; }
* { box-sizing: border-box; } body { margin: 0; } main { max-width: 660px; margin: auto; padding: 20px 14px 36px; }
a { display: inline-block; min-height: 44px; padding: 11px 0; color: #176c9d; font-weight: 700; }
a:focus-visible { outline: 3px solid #d99716; outline-offset: 4px; }
h1 { font-size: 27px; letter-spacing: -.03em; margin: 10px 0 6px; } h2 { font-size: 19px; margin: 0 0 10px; }
h3 { font-size: 15px; margin: 18px 0 10px; }
p { font-size: 14px; line-height: 1.5; margin: 8px 0; } .muted { color: #506b7b; }
section, main > details { margin-top: 16px; padding: 18px; background: #fff; border: 1px solid #d8e7ee; border-radius: 14px; }
summary { cursor: pointer; font-weight: 700; padding: 2px 0; min-height: 44px; }
summary:focus-visible { outline: 3px solid #d99716; outline-offset: 4px; }
summary .muted { display: block; padding-top: 6px; font-size: 12px; font-weight: 400; }
.details-body { padding-top: 10px; } .status { font-weight: 700; } .warning { color: #754708; background: #fff2d4; border-radius: 8px; padding: 9px 11px; }
[hidden] { display: none; } dl { margin: 14px 0 10px; display: grid; grid-template-columns: 1fr auto; gap: 12px 14px; }
dt { font-size: 13px; line-height: 1.4; align-self: center; } dd { margin: 0; text-align: right; font-size: 21px; font-weight: 750; font-variant-numeric: tabular-nums; }
.times { font-size: 12px; color: #506b7b; } ul { list-style: none; padding: 0; margin: 0; }
li { font-size: 14px; line-height: 1.5; padding: 11px 0; border-top: 1px solid #e5edf1; overflow-wrap: anywhere; }
li:first-child { border-top: 0; padding-top: 0; } li strong { display: block; } li p { margin: 3px 0; }
code { font-size: 12px; overflow-wrap: anywhere; color: #174c6b; } footer { font-size: 12px; color: #506b7b; padding-top: 20px; }
@media (max-width: 350px) { section { padding: 14px; } dd { font-size: 18px; } dt { font-size: 12px; } }
"""

_UI = r"""
  let summaryData = null, summaryConnection = "loading", summaryBusy = false;
  function summaryMoney(value, signed) {
    if (typeof value !== "number" || !isFinite(value)) return "Not reported";
    const sign = value < 0 ? "−" : signed && value > 0 ? "+" : "";
    return sign + "$" + Math.abs(value).toFixed(2);
  }
  function summaryAge(age) {
    if (age === null || !isFinite(age)) return "time unknown";
    if (age < 60) return "less than a minute ago";
    if (age < 3600) return Math.floor(age / 60) + " minutes ago";
    if (age < 86400) return Math.floor(age / 3600) + " hours ago";
    return Math.floor(age / 86400) + " days ago";
  }
  function summaryFee(value) {
    if (typeof value !== "number" || !isFinite(value) || value < 0) return "Not reported";
    if (value > 0 && value < .0001) return "<$0.0001";
    return value > 0 && value < .01 ? "$" + value.toFixed(4) : summaryMoney(value, false);
  }
  function summaryQuantity(value) { return value === null ? "Not reported" : String(value); }
  function summaryText(id, text) {
    const node = document.getElementById(id); if (node.textContent !== text) node.textContent = text;
  }
  function summaryWarning(id, messages) {
    const node = document.getElementById(id);
    const text = messages.join(" "); if (node.textContent !== text) node.textContent = text;
    node.hidden = messages.length === 0;
  }
  function summaryList(id, rows) {
    const list = document.getElementById(id), children = [];
    rows.forEach(function (row) {
      const item = document.createElement("li"), name = document.createElement("strong");
      name.textContent = row.name; item.appendChild(name);
      row.lines.forEach(function (line) {
        const p = document.createElement("p"); p.textContent = line; item.appendChild(p);
      });
      children.push(item);
    });
    list.replaceChildren.apply(list, children);
  }
  function summaryBusiness(prefix, venue, available) {
    summaryText(prefix + "-business-time", available
      ? (venue.current ? "Saved source: " : "Last saved source: ") + summaryAge(venue.age) + ". " + venue.sourceNote
      : "Waiting for venue connection details.");
    summaryText(prefix + "-business-basis", venue.positionsBasis ? "Positions: " + venue.positionsBasis : "Position source not reported.");
    summaryWarning(prefix + "-business-warning", venue.issues);
    const rows = [], positions = venue.positions.slice(0, 8), orders = venue.orders.slice(0, 8);
    positions.forEach(function (p) {
      const scope = p.scope === "owner" ? "Your own bet" : p.scope === "bot" ? "Bot bet" : "Owner/bot not identified";
      const lines = [
        scope + " · " + (p.side || "Side not reported") + " · Contracts: " + summaryQuantity(p.quantity) + ".",
        "Recorded cost: " + summaryMoney(p.cost, false) + "; price: " + summaryMoney(p.price, false) + ".",
        "Fee: " + summaryFee(p.fee) + (p.feeBasis ? " (" + p.feeBasis + ")" : " (basis not reported)") + ".",
      ];
      if (p.statusNote) lines.push(p.statusNote);
      rows.push({ name: "Position · " + (p.title || "Market not reported"), lines: lines });
    });
    orders.forEach(function (o) {
      rows.push({ name: "Order · " + (o.title || "Market not reported"), lines: [
        (o.side || "Side not reported") + " · " + o.status + ".",
        "Contracts: " + summaryQuantity(o.quantity) + "; filled: " + summaryQuantity(o.filled)
          + "; remaining: " + summaryQuantity(o.remaining) + ".",
        "Money reserved: " + summaryMoney(o.reserved, false) + ". An order is not a confirmed fill or profit.",
      ] });
    });
    if (!rows.length) rows.push({ name: available ? "Saved positions and orders" : "Venue details unavailable",
      lines: [available ? "No positions or orders listed in this saved report." : "Missing records do not mean zero holdings or fees."] });
    summaryList(prefix + "-business", rows);
    const clipped = venue.positions.length > positions.length || venue.orders.length > orders.length
      || venue.truncated.positions === true || venue.truncated.orders === true;
    summaryText(prefix + "-business-more", clipped ? "Only the first saved positions and orders are shown; this is not the full account history." : "");
  }
  function summaryActivity(id, events, venueName) {
    summaryList(id, events.length ? events.slice(0, 12).map(function (e) {
      const lines = [e.text, "Recorded " + summaryAge(e.age) + (e.current ? "." : "; awaiting a current source check.")];
      if (e.fee !== null) lines.push("Recorded fee: " + summaryFee(e.fee)
        + (e.feeBasis ? " (" + e.feeBasis + ")" : " (basis not reported)") + ".");
      return { name: venueName + (e.scope === "owner" ? " · Your activity" : " · Bot activity"), lines: lines };
    }) : [{ name: "No recorded " + venueName + " activity available",
      lines: ["Waiting for real order, fill or settlement records. Missing records are not proof of an empty account."] }]);
  }
  function summaryRender() {
    const s = tycoonSummary(summaryData, Date.now() / 1000), k = s.accounts.kalshi;
    const disconnected = summaryConnection === "offline", locked = summaryConnection === "locked";
    const message = locked ? "Session expired. Open your private town link again."
      : disconnected ? "Connection lost. Any figures below are the last saved report, not a current check."
      : summaryConnection === "loading" ? "Connecting to your town…"
      : s.pageStale ? "The saved page report is delayed. Check each account’s time below."
      : s.updated === null ? "Waiting for a valid town report. Missing numbers are not zero."
      : "Kalshi town summary. Cash and bot profit are separate.";
    summaryText("connection", message);
    const alerts = summaryData && Array.isArray(summaryData.alerts) ? summaryData.alerts : [];
    const serviceMessages = alerts.slice(0, 3).map(function (a) {
      return a && typeof a.text === "string" ? a.text : "";
    }).filter(Boolean);
    summaryWarning("service-warning", serviceMessages);
    summaryText("background-status", serviceMessages.length
      ? serviceMessages.length + " service notice(s) to review. Practice results never grow the town."
      : "Practice and public observations run separately; their results never grow the town.");
    const history = disconnected ? "Last report: " : "";
    summaryText("pm-mode", "Polymarket US · " + (s.on === true ? "LIVE setting"
      : s.on === false ? "PRACTICE setting" : "mode not reported"));
    summaryText("pm-state", history + s.stateText);
    summaryText("pm-cash", summaryMoney(s.cash, false));
    summaryText("pm-profit", summaryMoney(s.today, true));
    summaryText("pm-open", s.count === null ? "Not reported" : String(s.count));
    summaryText("pm-value", summaryMoney(s.value, false));
    summaryText("pm-times", "Cash checked " + summaryAge(s.cashAge) + "; holdings " + summaryAge(s.venueAge)
      + "; Pacific profit " + summaryAge(s.todayAge) + ".");
    const pmWarnings = [];
    if (s.stale) pmWarnings.push("The Polymarket desk report is delayed.");
    if (s.cash !== null && (s.cashStale || s.cashAsOf === null)) pmWarnings.push("Cash may be old; waiting for a fresh balance read.");
    if (s.count !== null && (s.venueStale || s.venueAsOf === null)) pmWarnings.push("Holdings may be old.");
    if (s.todayStale) pmWarnings.push("Pacific-day profit may be old.");
    if (s.todayStatus !== "ok") pmWarnings.push(s.todayReason || "A complete Pacific-day bot result is not available yet.");
    summaryWarning("pm-warning", pmWarnings);
    const pmIssues = s.business.venues.polymarket_us.issues;
    summaryText("pm-overview", history + s.stateText + ". "
      + (pmWarnings.length ? pmWarnings[0] : pmIssues.length ? pmIssues[0] : "This account is separate from the Kalshi town.")
      + (s.on === false ? " Existing real bets can still settle." : ""));
    summaryText("kalshi-state", history + (k.active ? "REAL MONEY (Kalshi) · " + k.stateText
      : k.practice ? "PRACTICE (Kalshi) · " + k.stateText : k.stateText));
    summaryText("kalshi-cash", summaryMoney(k.cash, false));
    summaryText("kalshi-profit", summaryMoney(k.today, true));
    summaryText("kalshi-pacific-profit", summaryMoney(k.todayPacific.value, true));
    summaryText("kalshi-risk", summaryMoney(k.exposure, false));
    summaryText("kalshi-reserved", summaryMoney(k.reserved, false));
    summaryText("kalshi-times", "Desk report " + summaryAge(k.age) + "; cash read " + summaryAge(k.cashAge)
      + "; Pacific profit " + summaryAge(k.todayPacific.age) + ". "
      + (k.accountAt ? "Account reconciliation " + summaryAge(k.accountAge) + "."
        : "Account reconciliation time not reported."));
    summaryText("kalshi-reason", k.reason || "Kalshi has its own cash, positions and limits.");
    summaryText("kalshi-limits", "Reported limits: " + summaryMoney(k.limits.window, false)
      + " per window; " + summaryMoney(k.limits.open, false) + " open risk; "
      + summaryMoney(k.limits.day, false) + " UTC-day stop; " + summaryMoney(k.limits.total, false) + " total stop.");
    summaryText("kalshi-risk-note", (k.riskNote || "Money at risk and cash reserved for orders are different amounts.")
      + (k.reserveNote ? " " + k.reserveNote : ""));
    summaryText("kalshi-limits-note", (k.limitsNote || "These are the desk’s reported limits, not available cash or a guaranteed maximum loss.")
      + (k.stopNote ? " " + k.stopNote : ""));
    const kalshiWarnings = [];
    if (k.stale) kalshiWarnings.push("The Kalshi desk report is delayed or missing.");
    if (k.cashStale) kalshiWarnings.push("A current Kalshi cash balance is not available.");
    if (k.todayStale) kalshiWarnings.push("The UTC-day result is delayed or unavailable.");
    if (!k.todayPacific.current) kalshiWarnings.push(k.todayPacific.reason
      || "A complete, current Pacific-day result is not available yet.");
    if (k.cleanupPending) kalshiWarnings.push("Resting-order cancellation and reconciliation are still pending.");
    if (k.accountAt && k.accountStale) kalshiWarnings.push("Account reconciliation may be old; a fresh desk report does not refresh it.");
    if (k.integrityError) kalshiWarnings.push(k.integrityNote || "Record check stopped new real buys: " + k.integrityError + ".");
    if (k.integrityReset) kalshiWarnings.push(k.integrityResetNote || "Record-check reset: " + k.integrityReset
      + ". A reset request does not mean trading has resumed.");
    summaryWarning("kalshi-warning", kalshiWarnings);
    summaryBusiness("pm", s.business.venues.polymarket_us, s.business.available);
    summaryBusiness("kalshi", s.business.venues.kalshi, s.business.available);
    const kalshiActivity = s.activity.filter(function (e) { return e.venue === "kalshi"; });
    const pmActivity = s.business.activity.filter(function (e) { return e.venue === "polymarket_us"; });
    summaryActivity("activity", kalshiActivity, "Kalshi");
    summaryActivity("pm-activity", pmActivity, "Polymarket US");
    summaryText("activity-more", kalshiActivity.length > 12 || s.business.venues.kalshi.truncated.events === true
      ? "Recent saved Kalshi events only; this is not the full account history." : "");
    summaryText("pm-activity-more", pmActivity.length > 12 || s.business.venues.polymarket_us.truncated.events === true
      ? "Recent saved Polymarket events only; this is not the full account history." : "");
    const work = { working: "Recently active", waiting: "Waiting", idle: "Idle", stuck: "Needs attention", unknown: "No current report" };
    summaryList("crew", s.crew.length ? s.crew.map(function (c) {
      return { name: c.name + " · " + c.job,
        lines: [(c.practice === true ? "PRACTICE. " : c.practice === false ? "REAL DESK. " : "Shared team role. ")
          + history + (work[c.status] || work.unknown) + ". " + c.doing,
          "Activity recorded " + summaryAge(c.age) + "."] };
    }) : [{ name: "Your team", lines: ["Waiting for a crew report."] }]);
    summaryList("research", s.research.map(function (r) {
      const lines = [history + r.status];
      if (r.count !== null) lines.push("Recorded: " + r.count + " " + r.countLabel + ".");
      lines.push(r.timeLabel + " " + summaryAge(r.age) + ".");
      return { name: r.name + " · " + r.scope, lines: lines };
    }));
  }
  async function summaryPoll() {
    if (document.hidden || summaryBusy || summaryConnection === "locked") return;
    summaryBusy = true;
    const controller = new AbortController(), timeout = setTimeout(function () { controller.abort(); }, 8000);
    try {
      const response = await fetch("/api/page", { method: "GET", credentials: "same-origin", mode: "same-origin",
        cache: "no-store", redirect: "error", headers: { Accept: "application/json" }, signal: controller.signal });
      if (response.status === 401 || response.status === 403) {
        summaryData = null; summaryConnection = "locked";
      } else {
        if (!response.ok) throw new Error("report_unavailable");
        const value = await response.json();
        if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid_report");
        summaryData = value; summaryConnection = "ready";
      }
    } catch (error) { summaryConnection = "offline"; }
    finally { clearTimeout(timeout); summaryBusy = false; summaryRender(); }
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { summaryRender(); summaryPoll(); } });
  setInterval(function () { if (!document.hidden) summaryRender(); }, 1000);
  setInterval(summaryPoll, 15000);
  summaryRender(); summaryPoll();
"""

_SCRIPT = "(function () {\n\"use strict\";\n" + TYCOON_DATA + _UI + "\n})();"


def _hash_source(value: str) -> str:
    digest = base64.b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


SUMMARY_CSP = (
    f"default-src 'none'; script-src {_hash_source(_SCRIPT)}; style-src {_hash_source(_STYLE)}; "
    "connect-src 'self'; base-uri 'none'; object-src 'none'; form-action 'none'; frame-ancestors 'none'"
)


def render_summary_html() -> str:
    """Return the static fallback; neither settings nor account records enter its HTML."""
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer"><title>Your Kalshi town · Summary</title>'
        f"<style>{_STYLE}</style></head><body><main>"
        '<header><a href="/">← Back to town</a><h1>Your Kalshi town</h1>'
        '<p class="muted">Kalshi’s real account, orders and results. The other desks are below.</p>'
        '<p id="connection" role="status" aria-live="polite">Connecting to your town…</p></header>'
        '<noscript><p class="warning">JavaScript is needed to read current reports. No account figures have been loaded.</p></noscript>'
        '<section aria-labelledby="kalshi-title"><h2 id="kalshi-title">Kalshi</h2>'
        '<p id="kalshi-state" class="status">No current Kalshi report</p>'
        '<dl><dt>Account cash</dt><dd id="kalshi-cash">Not reported</dd>'
        '<dt>Bot profit since midnight Pacific</dt><dd id="kalshi-pacific-profit">Not reported</dd>'
        '<dt>Bot worst-case loss still at risk</dt><dd id="kalshi-risk">Not reported</dd>'
        '<dt>Cash reserved for bot orders</dt><dd id="kalshi-reserved">Not reported</dd></dl>'
        '<p id="kalshi-reason" class="muted">Kalshi has its own cash, positions and limits.</p>'
        '<p id="kalshi-times" class="times">Report times unknown.</p><p id="kalshi-warning" class="warning" hidden></p>'
        '<h3>Recorded holdings and orders</h3><p id="kalshi-business-time" class="times"></p>'
        '<p id="kalshi-business-basis" class="muted"></p><p id="kalshi-business-warning" class="warning" hidden></p>'
        '<ul id="kalshi-business"><li>Waiting for venue details.</li></ul><p id="kalshi-business-more" class="muted"></p>'
        '<details><summary>Limits and the UTC stop clock</summary><div class="details-body">'
        '<dl><dt>Bot profit since midnight UTC</dt><dd id="kalshi-profit">Not reported</dd></dl>'
        '<p class="muted">The Pacific and UTC results cover different hours. They are not added together. Cash is not profit.</p>'
        '<p id="kalshi-risk-note" class="muted"></p><p id="kalshi-limits" class="muted"></p>'
        '<p id="kalshi-limits-note" class="muted"></p></div></details></section>'
        '<section aria-labelledby="activity-title"><h2 id="activity-title">Kalshi activity</h2>'
        '<p class="muted">Real order receipts, fills and settlements. Orders and fills are not profit.</p>'
        '<ul id="activity"><li>Waiting for Kalshi records.</li></ul><p id="activity-more" class="muted"></p>'
        '<p class="muted">The town grows from Kalshi bot profit since midnight Pacific, only when its book is complete and current. '
        'Losses can remove gardens, and midnight resets them. Deposits, your own bets, Polymarket results and practice results do not count.</p></section>'
        '<details id="other-account"><summary>Other live account<span id="pm-mode" class="muted">Polymarket US · mode not reported</span>'
        '<span id="pm-overview" class="muted">Waiting for this account’s status.</span></summary><div class="details-body">'
        '<h2 id="pm-title">Polymarket US</h2><p id="pm-state" class="status">No current desk report</p>'
        '<dl><dt>Available account cash</dt><dd id="pm-cash">Not reported</dd>'
        '<dt>Bot profit since midnight Pacific</dt><dd id="pm-profit">Not reported</dd>'
        '<dt>Account’s open markets</dt><dd id="pm-open">Not reported</dd>'
        '<dt>Reported value of those holdings</dt><dd id="pm-value">Not reported</dd></dl>'
        '<p class="muted">Cash and holdings include your own bets. Bot profit excludes your own bets, deposits and practice results. '
        'This account’s trading mode has not changed with the town view.</p>'
        '<p id="pm-times" class="times">Report times unknown.</p><p id="pm-warning" class="warning" hidden></p>'
        '<h3>Recorded holdings and orders</h3><p id="pm-business-time" class="times"></p>'
        '<p id="pm-business-basis" class="muted"></p><p id="pm-business-warning" class="warning" hidden></p>'
        '<ul id="pm-business"><li>Waiting for venue details.</li></ul><p id="pm-business-more" class="muted"></p>'
        '<h3>Polymarket activity</h3><ul id="pm-activity"><li>Waiting for Polymarket records.</li></ul>'
        '<p id="pm-activity-more" class="muted"></p></div></details>'
        '<details id="background"><summary>Team and background research<span id="background-status" class="muted">'
        'Practice and public observations are separate from real money.</span></summary><div class="details-body">'
        '<h2 id="crew-title">Your team</h2><ul id="crew"><li>Waiting for a crew report.</li></ul>'
        '<h3 id="research-title">Practice and observation reports</h3>'
        '<ul id="research"><li>Waiting for observation reports.</li></ul>'
        '<h3>Background service notices</h3><p class="muted">These messages cover the wider service; they do not establish Kalshi’s trading mode.</p>'
        '<p id="service-warning" class="warning" hidden></p></div></details>'
        '<details id="stop-help"><summary>How to stop real orders</summary><div class="details-body">'
        '<p>On Railway’s bot service, set both <code>POLYDESK_MODE=paper</code> and '
        '<code>SPEEDDESK_KALSHI_MODE=paper</code>.</p>'
        '<p>After the restart, verify that both desks have stopped new real buys. Confirm that Kalshi’s resting bids were cancelled and remaining exposure was reconciled.</p>'
        '<p>Already filled bets stay open and can still win or lose. This summary cannot change trading settings or place orders.</p></div></details>'
        '<footer>Read only · checks for reports every 15 seconds while this page is visible.</footer>'
        f"</main><script>{_SCRIPT}</script></body></html>\n"
    )
