import { NextRequest, NextResponse } from "next/server";
import { sql } from "@vercel/postgres";
import { runSeed } from "@/db/seed";

export const maxDuration = 60;

// One-click first-run setup. Called after the initial Vercel deploy to
// create all tables and seed the plant, users, raw materials, panel types,
// BOMs, and initial stock. Safe to re-run: both steps are idempotent.
//
// Guarded by CRON_SECRET to keep strangers out.
export async function GET(req: NextRequest) {
  const provided =
    req.nextUrl.searchParams.get("secret") ??
    (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const expected = process.env.CRON_SECRET;
  if (!expected) {
    return NextResponse.json(
      { error: "CRON_SECRET is not set on the server" },
      { status: 500 }
    );
  }
  if (provided !== expected) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const log: string[] = [];
  const push = (m: string) => {
    log.push(m);
    console.log(m);
  };

  try {
    push("Creating tables (if missing)…");
    await createTables();
    push("Tables ready.");
    await runSeed(push);
    return NextResponse.json({ ok: true, log });
  } catch (err) {
    console.error("/api/admin/init failed", err);
    return NextResponse.json(
      {
        ok: false,
        error: err instanceof Error ? err.message : "Failed",
        log,
      },
      { status: 500 }
    );
  }
}

async function createTables() {
  // Raw SQL so this works without the drizzle-kit CLI.
  await sql`CREATE EXTENSION IF NOT EXISTS "pgcrypto"`;

  await sql`CREATE TABLE IF NOT EXISTS plants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    address text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
  )`;

  await sql`CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE,
    name text NOT NULL,
    role text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    receive_alerts boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
  )`;

  await sql`CREATE TABLE IF NOT EXISTS raw_materials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    sku_code text,
    unit text NOT NULL,
    category text NOT NULL,
    reorder_point integer,
    reorder_qty integer,
    vendor text,
    buy_america boolean NOT NULL DEFAULT false,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
  )`;

  await sql`CREATE TABLE IF NOT EXISTS raw_material_stock (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_material_id uuid NOT NULL REFERENCES raw_materials(id) ON DELETE CASCADE,
    plant_id uuid NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    qty_on_hand integer NOT NULL DEFAULT 0,
    last_updated timestamptz NOT NULL DEFAULT now()
  )`;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS raw_material_stock_material_plant_uniq
    ON raw_material_stock (raw_material_id, plant_id)`;

  await sql`CREATE TABLE IF NOT EXISTS raw_material_lots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_material_id uuid NOT NULL REFERENCES raw_materials(id) ON DELETE CASCADE,
    plant_id uuid NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    lot_number text NOT NULL,
    vendor text,
    po_number text,
    qty_received integer NOT NULL,
    qty_remaining integer NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    received_by uuid REFERENCES users(id),
    notes text
  )`;

  await sql`CREATE TABLE IF NOT EXISTS panel_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sku_code text NOT NULL UNIQUE,
    length_ft integer NOT NULL,
    plate_type text NOT NULL,
    tie_type text NOT NULL,
    rail_weight integer NOT NULL,
    fastener_type text NOT NULL,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true
  )`;

  await sql`CREATE TABLE IF NOT EXISTS bom_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    panel_type_id uuid NOT NULL REFERENCES panel_types(id) ON DELETE CASCADE,
    raw_material_id uuid NOT NULL REFERENCES raw_materials(id) ON DELETE CASCADE,
    qty_per_panel integer NOT NULL
  )`;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS bom_lines_panel_material_uniq
    ON bom_lines (panel_type_id, raw_material_id)`;

  await sql`CREATE TABLE IF NOT EXISTS finished_goods_stock (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    panel_type_id uuid NOT NULL REFERENCES panel_types(id) ON DELETE CASCADE,
    plant_id uuid NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    qty_on_hand integer NOT NULL DEFAULT 0,
    last_updated timestamptz NOT NULL DEFAULT now()
  )`;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS finished_goods_stock_panel_plant_uniq
    ON finished_goods_stock (panel_type_id, plant_id)`;

  await sql`CREATE TABLE IF NOT EXISTS build_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    panel_type_id uuid NOT NULL REFERENCES panel_types(id),
    plant_id uuid NOT NULL REFERENCES plants(id),
    qty_built integer NOT NULL,
    rail_waste_ft integer NOT NULL DEFAULT 0,
    built_at timestamptz NOT NULL DEFAULT now(),
    built_by uuid REFERENCES users(id),
    notes text
  )`;

  await sql`CREATE TABLE IF NOT EXISTS build_event_consumption (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    build_event_id uuid NOT NULL REFERENCES build_events(id) ON DELETE CASCADE,
    raw_material_id uuid NOT NULL REFERENCES raw_materials(id),
    qty_consumed integer NOT NULL,
    lot_id uuid REFERENCES raw_material_lots(id)
  )`;

  await sql`CREATE TABLE IF NOT EXISTS shipment_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    panel_type_id uuid NOT NULL REFERENCES panel_types(id),
    plant_id uuid NOT NULL REFERENCES plants(id),
    qty_shipped integer NOT NULL,
    customer text NOT NULL DEFAULT 'BNSF',
    po_number text,
    shipped_at timestamptz NOT NULL DEFAULT now(),
    shipped_by uuid REFERENCES users(id),
    notes text
  )`;

  await sql`CREATE TABLE IF NOT EXISTS alert_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_material_id uuid NOT NULL REFERENCES raw_materials(id) ON DELETE CASCADE,
    plant_id uuid NOT NULL REFERENCES plants(id) ON DELETE CASCADE,
    qty_at_alert integer NOT NULL,
    reorder_point integer NOT NULL,
    sent_at timestamptz NOT NULL DEFAULT now(),
    recipients text[] NOT NULL
  )`;

  await sql`CREATE TABLE IF NOT EXISTS login_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
  )`;
}
