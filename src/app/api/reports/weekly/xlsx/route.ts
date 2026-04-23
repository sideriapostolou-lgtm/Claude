import { NextResponse } from "next/server";
import ExcelJS from "exceljs";
import {
  getVancouverPlant,
  getRawMaterialsWithStock,
  getFinishedGoodsWithStock,
  getLowStockItems,
} from "@/lib/queries";
import { requireUser } from "@/lib/session";
import { format } from "date-fns";

export async function GET() {
  try {
    await requireUser();
  } catch {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const plant = await getVancouverPlant();
  const [raw, finished, low] = await Promise.all([
    getRawMaterialsWithStock(plant.id),
    getFinishedGoodsWithStock(plant.id),
    getLowStockItems(plant.id),
  ]);

  const wb = new ExcelJS.Workbook();
  wb.creator = "Omega Inventory";
  wb.created = new Date();

  const header = (ws: ExcelJS.Worksheet, cols: string[]) => {
    ws.addRow(cols);
    ws.getRow(1).font = { bold: true, color: { argb: "FFFFFFFF" } };
    ws.getRow(1).fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: "FF1F3864" },
    };
  };

  // Low stock sheet (first)
  if (low.length) {
    const ws = wb.addWorksheet("Low stock");
    header(ws, [
      "Material",
      "Category",
      "On hand",
      "Reorder point",
      "Reorder qty",
      "Vendor",
    ]);
    for (const m of low) {
      ws.addRow([
        m.name,
        m.category,
        m.qtyOnHand,
        m.reorderPoint,
        m.reorderQty,
        m.vendor ?? "",
      ]);
    }
    ws.columns.forEach((c) => (c.width = 22));
  }

  // Raw materials
  const wsRaw = wb.addWorksheet("Raw materials");
  header(wsRaw, ["Name", "Category", "Unit", "On hand", "Reorder point", "Vendor"]);
  for (const m of raw) {
    wsRaw.addRow([m.name, m.category, m.unit, m.qtyOnHand, m.reorderPoint ?? "", m.vendor ?? ""]);
  }
  wsRaw.columns.forEach((c) => (c.width = 22));

  // Finished goods
  const wsFg = wb.addWorksheet("Finished goods");
  header(wsFg, ["SKU", "Description", "Length (ft)", "Plate", "Rail #", "On hand"]);
  for (const p of finished) {
    wsFg.addRow([p.skuCode, p.displayName, p.lengthFt, p.plateType, p.railWeight, p.qtyOnHand]);
  }
  wsFg.columns.forEach((c) => (c.width = 22));

  // Summary sheet
  const ws = wb.addWorksheet("Summary");
  ws.addRow(["Omega Industries — Track Panel Inventory"]);
  ws.getRow(1).font = { bold: true, size: 14 };
  ws.addRow([`${plant.name} — ${format(new Date(), "MMMM d, yyyy")}`]);
  ws.addRow([]);
  ws.addRow(["Finished panels on hand", finished.reduce((s, p) => s + p.qtyOnHand, 0)]);
  ws.addRow(["Raw material SKUs below reorder", low.length]);
  ws.columns.forEach((c) => (c.width = 36));

  const buffer = await wb.xlsx.writeBuffer();
  const filename = `omega-inventory-${format(new Date(), "yyyyMMdd")}.xlsx`;

  return new NextResponse(buffer, {
    headers: {
      "Content-Type":
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "Content-Disposition": `attachment; filename="${filename}"`,
    },
  });
}
