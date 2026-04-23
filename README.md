# Omega Inventory

Internal track-panel inventory app for Omega Industries — Vancouver, WA plant.
Tracks raw materials, finished track panels, and BOM-driven build/shipment
events. Nightly low-stock alerts via email.

## Stack

- **Next.js 14** (App Router) + TypeScript + Tailwind CSS
- **Vercel Postgres** + **Drizzle ORM** for the data layer
- **iron-session** magic-link auth (no passwords) + **Resend** for email
- **Vercel Cron** for nightly low-stock alerts
- **recharts** + **ExcelJS** for dashboard and weekly-report export

## Getting started

```bash
pnpm install
cp .env.example .env.local
# fill in POSTGRES_URL, RESEND_API_KEY, SESSION_SECRET (openssl rand -hex 32), CRON_SECRET
pnpm db:push       # create tables
pnpm db:seed       # seed plant, users, raw materials, panels, BOMs, initial stock
pnpm dev
```

Open http://localhost:3000 and log in with one of the seeded emails
(`sideri@`, `argyro@`, `serafim@omega-industries.com`). You'll get a
one-click magic link by email.

## Scripts

- `pnpm dev` — Next dev server
- `pnpm build` / `pnpm start` — production build and run
- `pnpm typecheck` — `tsc --noEmit`
- `pnpm db:generate` — generate migration SQL from schema changes
- `pnpm db:push` — push schema directly to the DB (used for first deploy)
- `pnpm db:seed` — seed idempotently (safe to re-run)

## Deployment (Vercel)

1. Push this repo to GitHub and import into Vercel.
2. Add a Vercel Postgres integration; the `POSTGRES_URL*` env vars populate
   automatically.
3. Set the other env vars from `.env.example` in the Vercel project:
   `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `SESSION_SECRET`,
   `NEXT_PUBLIC_APP_URL`, `CRON_SECRET`.
4. After the first deploy, run `pnpm db:push` and `pnpm db:seed` (either
   locally against the prod URL, or via `vercel env pull` and a one-shot
   Node script). The `vercel.json` in this repo registers the nightly
   low-stock cron.
5. Point `inventory.omega-industries.com` at the Vercel deployment via GoDaddy
   DNS once the URL is confirmed.

## Routes

| Path | Access | What |
|---|---|---|
| `/` | any user | Dashboard: metrics, low-stock alerts, recent activity, chart |
| `/raw-materials` | any user | List + filter + search |
| `/raw-materials/[id]` | any user | Lot history, consumption, edit reorder points (admin) |
| `/finished-goods` | any user | List all 36 panel types |
| `/finished-goods/[id]` | any user | BOM, on-hand, "can build X more", build/ship history |
| `/log/build` | admin | Log production event (atomic: consumes BOM, adds finished) |
| `/log/shipment` | admin | Log panels shipped out |
| `/log/receipt` | admin | Log new lot received |
| `/reports/weekly` | any user | Weekly report view + Excel download + email |
| `/admin/users` | admin | Manage whitelist |
| `/admin/panels` | admin | Edit panel display names + per-panel BOM qty |
| `/admin/bulk-count` | admin | Go-live full physical count, single-transaction save |
| `/api/cron/low-stock-alert` | Cron (Bearer) | Nightly at 15:00 UTC = 7:00 AM Pacific |

Preview the low-stock alert (no email sent) at
`/api/cron/low-stock-alert?preview=1`.

## Data model

All tables in `src/db/schema.ts`. Key tables:

- `raw_materials` / `raw_material_stock` / `raw_material_lots`
- `panel_types` / `bom_lines` / `finished_goods_stock`
- `build_events` / `build_event_consumption` / `shipment_events`
- `plants`, `users`, `alert_log`, `login_tokens`

Build events run in a DB transaction: decrement BOM materials, insert
consumption rows, increment finished-goods. If any step fails, the whole
build is rolled back.

## BOM math

Source of truth: `src/db/bom.ts`. Per Sideri's 4/22/26 revision:

- Only 80' rail sticks are stocked. 40' panels use 1 stick, 60' panels use
  2 sticks with 40ft scrap recorded, 80' panels use 2 sticks no scrap.
- Per-foot items (ties, tie plates, anchors, spikes, Pandrol clips) scale
  linearly from the 40' baseline.
- Joint bars (4) and track bolts (8) are fixed per panel regardless of length.
- Standard panels: cut spikes + bar-stock anchors. Pandrol panels: screw
  spikes + Pandrol E-clips (no anchors).

## Open items for Sideri at launch

- **Orphaned 20× "141# 40' Rail"** from the 4/3/26 report. No longer a
  stocked SKU (40' is cut from 80'). Decide: convert to `10× 80'
  equivalents`, one-off legacy SKU, or physical re-verify. Not seeded.
- Reorder quantities (`reorder_qty`) are blank — fill in via
  `/raw-materials/[id]` or bulk-count page.
- Go-live physical count: use `/admin/bulk-count` to overwrite every
  on-hand number in a single transaction.
