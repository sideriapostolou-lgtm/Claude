import { NextRequest, NextResponse } from "next/server";
import { db, schema } from "@/db";
import { and, eq, gte, sql } from "drizzle-orm";
import { getVancouverPlant, getLowStockItems } from "@/lib/queries";
import { sendEmail } from "@/lib/email";
import { format } from "date-fns";

export async function GET(req: NextRequest) {
  const preview = req.nextUrl.searchParams.get("preview") === "1";
  const auth = req.headers.get("authorization") ?? "";
  const providedFromBearer = auth.startsWith("Bearer ")
    ? auth.slice(7)
    : "";

  if (!preview) {
    const expected = process.env.CRON_SECRET;
    if (!expected) {
      return NextResponse.json({ error: "CRON_SECRET not set" }, { status: 500 });
    }
    if (providedFromBearer !== expected) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
  }

  const plant = await getVancouverPlant();
  const low = await getLowStockItems(plant.id);

  // Skip items alerted in the last 24 hours.
  const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
  const recentAlerts = await db
    .select()
    .from(schema.alertLog)
    .where(
      and(
        eq(schema.alertLog.plantId, plant.id),
        gte(schema.alertLog.sentAt, dayAgo)
      )
    );
  const recentlyAlerted = new Set(recentAlerts.map((a) => a.rawMaterialId));
  const toAlert = low.filter((m) => !recentlyAlerted.has(m.id));

  const recipients = await db
    .select()
    .from(schema.users)
    .where(and(eq(schema.users.active, true), eq(schema.users.receiveAlerts, true)));

  if (preview) {
    return NextResponse.json({
      plant: plant.name,
      totalBelowReorder: low.length,
      wouldAlert: toAlert.length,
      suppressed: low.length - toAlert.length,
      recipients: recipients.map((r) => r.email),
      items: toAlert.map((m) => ({
        name: m.name,
        qtyOnHand: m.qtyOnHand,
        reorderPoint: m.reorderPoint,
        reorderQty: m.reorderQty,
      })),
    });
  }

  if (toAlert.length === 0 || recipients.length === 0) {
    return NextResponse.json({ ok: true, sent: 0, note: "nothing to alert" });
  }

  const html = renderAlertHtml({
    plant: plant.name,
    items: toAlert,
  });
  const emailList = recipients.map((r) => r.email);
  await sendEmail({
    to: emailList,
    subject: `⚠ Omega Inventory — ${toAlert.length} item${
      toAlert.length === 1 ? "" : "s"
    } below reorder point`,
    html,
  });

  await db.insert(schema.alertLog).values(
    toAlert.map((m) => ({
      rawMaterialId: m.id,
      plantId: plant.id,
      qtyAtAlert: m.qtyOnHand,
      reorderPoint: m.reorderPoint ?? 0,
      recipients: emailList,
    }))
  );

  return NextResponse.json({
    ok: true,
    sent: toAlert.length,
    recipients: emailList.length,
  });
}

function renderAlertHtml({
  plant,
  items,
}: {
  plant: string;
  items: Array<{
    name: string;
    qtyOnHand: number;
    reorderPoint: number | null;
    reorderQty: number | null;
    vendor: string | null;
    unit: string;
  }>;
}) {
  const esc = (s: string | number | null | undefined) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!)
    );
  return `
    <div style="font-family:Inter,-apple-system,Segoe UI,sans-serif;color:#14213d;max-width:640px;margin:0 auto;padding:24px">
      <h1 style="color:#c00;margin:0 0 4px">Low-stock alert</h1>
      <p style="color:#6b7280;margin:0 0 16px">${esc(plant)} · ${esc(format(new Date(), "MMMM d, yyyy"))}</p>
      <p>${items.length} raw material${items.length === 1 ? " has" : "s have"} dropped below reorder point:</p>
      <table style="border-collapse:collapse;width:100%;font-size:13px;margin-top:8px">
        <thead>
          <tr style="background:#f3f4f6">
            <th style="padding:6px 8px;text-align:left">Material</th>
            <th style="padding:6px 8px;text-align:right">On hand</th>
            <th style="padding:6px 8px;text-align:right">Reorder pt</th>
            <th style="padding:6px 8px;text-align:right">Reorder qty</th>
            <th style="padding:6px 8px;text-align:left">Vendor</th>
          </tr>
        </thead>
        <tbody>
          ${items
            .map(
              (m) => `
            <tr style="background:#fff5f5">
              <td style="padding:6px 8px;border-bottom:1px solid #eee">${esc(m.name)}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:right;color:#c00;font-weight:600">${esc(m.qtyOnHand)} ${esc(m.unit)}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:right">${esc(m.reorderPoint ?? "")}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:right">${esc(m.reorderQty ?? "")}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #eee">${esc(m.vendor ?? "")}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>
      <p style="margin-top:20px">Log in to review: <a href="${esc(process.env.NEXT_PUBLIC_APP_URL ?? "")}">${esc(process.env.NEXT_PUBLIC_APP_URL ?? "")}</a></p>
    </div>
  `;
}
