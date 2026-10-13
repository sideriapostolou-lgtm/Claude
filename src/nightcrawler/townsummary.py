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
section { margin-top: 16px; padding: 18px; background: #fff; border: 1px solid #d8e7ee; border-radius: 14px; }
.status { font-weight: 700; } .warning { color: #754708; background: #fff2d4; border-radius: 8px; padding: 9px 11px; }
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
      ? (venue.current ? "Source checked " : "Last saved source: ") + summaryAge(venue.age) + ". " + venue.sourceNote
      : "Waiting for venue connection details.");
    summaryText(prefix + "-business-basis", venue.positionsBasis ? "Positions: " + venue.positionsBasis : "Position source not reported.");
    summaryWarning(prefix + "-business-warning", venue.issues);
    const rows = [], positions = venue.positions.slice(0, 8), orders = venue.orders.slice(0, 8);
    positions.forEach(function (p) {
      const scope = p.scope === "owner" ? "Your own bet" : p.scope === "bot" ? "Bot bet" : "Owner/bot not identified";
      rows.push({ name: "Position · " + (p.title || "Market not reported"), lines: [
        scope + " · " + (p.side || "Side not reported") + " · Contracts: " + summaryQuantity(p.quantity) + ".",
        "Recorded cost: " + summaryMoney(p.cost, false) + "; price: " + summaryMoney(p.price, false) + ".",
        "Fee: " + summaryFee(p.fee) + (p.feeBasis ? " (" + p.feeBasis + ")" : " (basis not reported)") + ".",
      ] });
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
  function summaryRender() {
    const s = tycoonSummary(summaryData, Date.now() / 1000), k = s.accounts.kalshi;
    const disconnected = summaryConnection === "offline", locked = summaryConnection === "locked";
    const message = locked ? "Session expired. Open your private town link again."
      : disconnected ? "Connection lost. Any figures below are the last saved report, not a current check."
      : summaryConnection === "loading" ? "Connecting to your town…"
      : s.pageStale ? "The saved page report is delayed. Check each account’s time below."
      : s.updated === null ? "Waiting for a valid town report. Missing numbers are not zero."
      : "Read-only town summary. Cash and bot profit are separate.";
    summaryText("connection", message);
    const alerts = summaryData && Array.isArray(summaryData.alerts) ? summaryData.alerts : [];
    summaryWarning("service-warning", alerts.slice(0, 3).map(function (a) {
      return a && typeof a.text === "string" ? a.text : "";
    }).filter(Boolean));
    const history = disconnected ? "Last report: " : "";
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
    if (s.todayStatus !== "ok") pmWarnings.push("A complete Pacific-day bot result is not available yet.");
    summaryWarning("pm-warning", pmWarnings);
    summaryText("kalshi-state", history + (k.active ? "REAL MONEY (Kalshi) · new real orders enabled"
      : k.practice ? "PRACTICE (Kalshi) · new real orders off" : k.stateText));
    summaryText("kalshi-cash", summaryMoney(k.cash, false));
    summaryText("kalshi-profit", summaryMoney(k.today, true));
    summaryText("kalshi-pacific-profit", summaryMoney(k.todayPacific.value, true));
    summaryText("kalshi-risk", summaryMoney(k.exposure, false));
    summaryText("kalshi-times", "Account checked " + summaryAge(k.age) + "; cash " + summaryAge(k.cashAge)
      + "; Pacific profit " + summaryAge(k.todayPacific.age) + ".");
    summaryText("kalshi-reason", k.reason || "Kalshi has its own cash, positions and limits.");
    const kalshiWarnings = [];
    if (k.stale) kalshiWarnings.push("The Kalshi desk report is delayed or missing.");
    if (k.cashStale) kalshiWarnings.push("A current Kalshi cash balance is not available.");
    if (k.todayStale) kalshiWarnings.push("The UTC-day result is delayed or unavailable.");
    if (!k.todayPacific.current) kalshiWarnings.push("A complete, current Pacific-day result is not available yet.");
    if (k.cleanupPending) kalshiWarnings.push("Resting-order cancellation and reconciliation are still pending.");
    summaryWarning("kalshi-warning", kalshiWarnings);
    summaryBusiness("pm", s.business.venues.polymarket_us, s.business.available);
    summaryBusiness("kalshi", s.business.venues.kalshi, s.business.available);
    summaryList("activity", s.activity.length ? s.activity.slice(0, 12).map(function (e) {
      const lines = [e.text, "Recorded " + summaryAge(e.age) + (e.current ? "." : "; awaiting a current source check.")];
      if (e.fee !== null) lines.push("Recorded fee: " + summaryFee(e.fee)
        + (e.feeBasis ? " (" + e.feeBasis + ")" : " (basis not reported)") + ".");
      return { name: (e.venue === "kalshi" ? "Kalshi" : "Polymarket US")
        + (e.scope === "owner" ? " · Your activity" : " · Bot activity"), lines: lines };
    }) : [{ name: "No recorded real activity available", lines: ["Waiting for venue order, fill or settlement records. Practice activity is separate."] }]);
    summaryText("activity-more", s.activity.length > 12 || s.business.venues.polymarket_us.truncated.events === true
      || s.business.venues.kalshi.truncated.events === true ? "Recent saved events only; this is not the full account history." : "");
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
        '<meta name="referrer" content="no-referrer"><title>Your town · Summary</title>'
        f"<style>{_STYLE}</style></head><body><main>"
        '<header><a href="/">← Back to town</a><h1>Your town, simply</h1>'
        '<p class="muted">The same account reports, without the 3D view.</p>'
        '<p id="connection" role="status" aria-live="polite">Connecting to your town…</p>'
        '<p id="service-warning" class="warning" hidden></p></header>'
        '<noscript><p class="warning">JavaScript is needed to read current reports. No account figures have been loaded.</p></noscript>'
        '<section aria-labelledby="pm-title"><h2 id="pm-title">Polymarket US</h2>'
        '<p id="pm-state" class="status">No current desk report</p>'
        '<dl><dt>Available account cash</dt><dd id="pm-cash">Not reported</dd>'
        '<dt>Bot profit since midnight Pacific</dt><dd id="pm-profit">Not reported</dd>'
        '<dt>Account’s open markets</dt><dd id="pm-open">Not reported</dd>'
        '<dt>Reported value of those holdings</dt><dd id="pm-value">Not reported</dd></dl>'
        '<p class="muted">Cash and holdings include your own bets. Bot profit excludes your own bets, deposits and practice results.</p>'
        '<p id="pm-times" class="times">Report times unknown.</p><p id="pm-warning" class="warning" hidden></p>'
        '<h3>Recorded holdings and orders</h3><p id="pm-business-time" class="times"></p>'
        '<p id="pm-business-basis" class="muted"></p><p id="pm-business-warning" class="warning" hidden></p>'
        '<ul id="pm-business"><li>Waiting for venue details.</li></ul><p id="pm-business-more" class="muted"></p></section>'
        '<section aria-labelledby="kalshi-title"><h2 id="kalshi-title">Kalshi</h2>'
        '<p id="kalshi-state" class="status">No current Kalshi report</p>'
        '<dl><dt>Account cash</dt><dd id="kalshi-cash">Not reported</dd>'
        '<dt>Bot profit since midnight Pacific</dt><dd id="kalshi-pacific-profit">Not reported</dd>'
        '<dt>Bot profit since midnight UTC</dt><dd id="kalshi-profit">Not reported</dd>'
        '<dt>Bot money at risk, including resting orders</dt><dd id="kalshi-risk">Not reported</dd></dl>'
        '<p id="kalshi-reason" class="muted">Kalshi has its own cash, positions and limits.</p>'
        '<p class="muted">The Pacific and UTC results cover different hours. They are not added together. Cash is not profit.</p>'
        '<p id="kalshi-times" class="times">Report times unknown.</p><p id="kalshi-warning" class="warning" hidden></p>'
        '<h3>Recorded holdings and orders</h3><p id="kalshi-business-time" class="times"></p>'
        '<p id="kalshi-business-basis" class="muted"></p><p id="kalshi-business-warning" class="warning" hidden></p>'
        '<ul id="kalshi-business"><li>Waiting for venue details.</li></ul><p id="kalshi-business-more" class="muted"></p></section>'
        '<section aria-labelledby="activity-title"><h2 id="activity-title">Recent real activity</h2>'
        '<p class="muted">Orders, fills and settlements from each venue. Your own activity stays separate from bot profit.</p>'
        '<ul id="activity"><li>Waiting for venue records.</li></ul><p id="activity-more" class="muted"></p></section>'
        '<section aria-labelledby="crew-title"><h2 id="crew-title">Your team</h2>'
        '<ul id="crew"><li>Waiting for a crew report.</li></ul></section>'
        '<section aria-labelledby="research-title"><h2 id="research-title">Research</h2>'
        '<p class="muted">Practice and public observations do not count as real profit.</p>'
        '<ul id="research"><li>Waiting for observation reports.</li></ul></section>'
        '<section aria-labelledby="growth-title"><h2 id="growth-title">How the town grows</h2>'
        '<p>Garden upgrades use both bots’ recorded profit since midnight Pacific, only when both books are complete and current. '
        'Losses can remove gardens, and midnight resets them. Deposits, your own bets and practice results do not count.</p></section>'
        '<section aria-labelledby="stop-title"><h2 id="stop-title">Stop new real orders</h2>'
        '<p>On Railway’s bot service, set both <code>POLYDESK_MODE=paper</code> and '
        '<code>SPEEDDESK_KALSHI_MODE=paper</code>.</p>'
        '<p>After the restart, verify that both desks have stopped new real buys. Confirm that Kalshi’s resting bids were cancelled and remaining exposure was reconciled.</p>'
        '<p>Already filled bets stay open and can still win or lose. This summary cannot change trading settings or place orders.</p></section>'
        '<footer>Read only · checks for reports every 15 seconds while this page is visible.</footer>'
        f"</main><script>{_SCRIPT}</script></body></html>\n"
    )
