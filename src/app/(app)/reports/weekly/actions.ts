"use server";

import {
  getVancouverPlant,
  getRawMaterialsWithStock,
  getFinishedGoodsWithStock,
  getLowStockItems,
} from "@/lib/queries";
import { db, schema } from "@/db";
import { and, eq } from "drizzle-orm";
import { sendEmail } from "@/lib/email";
import { requireUser } from "@/lib/session";
import { format } from "date-fns";

export async function emailWeeklyReport() {
  try {
    await requireUser();
    const plant = await getVancouverPlant();
    const [raw, finished, low] = await Promise.all([
      getRawMaterialsWithStock(plant.id),
      getFinishedGoodsWithStock(plant.id),
      getLowStockItems(plant.id),
    ]);

    const recipients = await db
      .select()
      .from(schema.users)
      .where(
        and(eq(schema.users.active, true), eq(schema.users.receiveAlerts, true))
      );
    if (recipients.length === 0) {
      return { ok: false as const, error: "No recipients configured" };
    }

    const subject = `Weekly inventory report — ${format(new Date(), "MMM d, yyyy")}`;
    const html = renderReportHtml({ plant: plant.name, raw, finished, low });

    await sendEmail({
      to: recipients.map((r) => r.email),
      subject,
      html,
    });

    return { ok: true as const, count: recipients.length };
  } catch (err) {
    console.error("emailWeeklyReport failed", err);
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}

function renderReportHtml(params: {
  plant: string;
  raw: Array<{ name: string; unit: string; qtyOnHand: number; reorderPoint: number | null }>;
  finished: Array<{ skuCode: string; displayName: string; qtyOnHand: number }>;
  low: Array<{ name: string; qtyOnHand: number; reorderPoint: number | null; reorderQty: number | null; vendor: string | null }>;
}) {
  const { plant, raw, finished, low } = params;
  const esc = (s: string | number | null | undefined) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!)
    );
  const row = (cells: (string | number)[], alert = false) =>
    `<tr${alert ? ' style="background:#ffecec"' : ""}>${cells
      .map(
        (c, i) =>
          `<td style="padding:6px 8px;border-bottom:1px solid #eee;${i > 0 ? "text-align:right" : ""};${alert ? "color:#c00;font-weight:600" : ""}">${esc(c)}</td>`
      )
      .join("")}</tr>`;

  return `
    <div style="font-family:Inter,-apple-system,Segoe UI,sans-serif;color:#14213d;max-width:720px;margin:0 auto;padding:24px">
      <h1 style="color:#1F3864;margin:0 0 4px">Omega Inventory — Weekly Report</h1>
      <p style="color:#6b7280;margin:0 0 20px">${esc(plant)} · ${esc(format(new Date(), "MMMM d, yyyy"))}</p>

      ${
        low.length
          ? `
        <h2 style="color:#c00;margin:16px 0 8px;font-size:16px">⚠ ${low.length} item${low.length === 1 ? "" : "s"} below reorder point</h2>
        <table style="border-collapse:collapse;width:100%;font-size:13px">
          <thead><tr style="background:#f3f4f6">
            <th style="padding:6px 8px;text-align:left">Material</th>
            <th style="padding:6px 8px;text-align:right">On hand</th>
            <th style="padding:6px 8px;text-align:right">Reorder pt</th>
            <th style="padding:6px 8px;text-align:right">Reorder qty</th>
            <th style="padding:6px 8px;text-align:left">Vendor</th>
          </tr></thead>
          <tbody>
            ${low.map((m) => row([m.name, m.qtyOnHand, m.reorderPoint ?? "", m.reorderQty ?? "", m.vendor ?? ""], true)).join("")}
          </tbody>
        </table>
      `
          : `<p style="color:#166534;background:#f0fdf4;padding:12px;border-radius:6px">All materials above reorder point.</p>`
      }

      <h2 style="color:#1F3864;margin:24px 0 8px;font-size:16px">Raw materials</h2>
      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead><tr style="background:#f3f4f6">
          <th style="padding:6px 8px;text-align:left">Name</th>
          <th style="padding:6px 8px;text-align:left">Unit</th>
          <th style="padding:6px 8px;text-align:right">Qty</th>
        </tr></thead>
        <tbody>
          ${raw.map((m) => row([m.name, m.unit, m.qtyOnHand])).join("")}
        </tbody>
      </table>

      <h2 style="color:#1F3864;margin:24px 0 8px;font-size:16px">Finished track panels</h2>
      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead><tr style="background:#f3f4f6">
          <th style="padding:6px 8px;text-align:left">SKU</th>
          <th style="padding:6px 8px;text-align:left">Description</th>
          <th style="padding:6px 8px;text-align:right">Qty</th>
        </tr></thead>
        <tbody>
          ${finished.map((p) => row([p.skuCode, p.displayName, p.qtyOnHand])).join("")}
        </tbody>
      </table>
    </div>
  `;
}
