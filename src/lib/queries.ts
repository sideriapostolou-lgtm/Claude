import "server-only";
import { db, schema } from "@/db";
import { and, desc, eq, lt, sql } from "drizzle-orm";

export async function getVancouverPlant() {
  const [plant] = await db
    .select()
    .from(schema.plants)
    .where(eq(schema.plants.code, "VAN"));
  if (!plant) throw new Error("Vancouver plant not seeded");
  return plant;
}

export async function getRawMaterialsWithStock(plantId: string) {
  const rows = await db
    .select({
      material: schema.rawMaterials,
      stock: schema.rawMaterialStock,
    })
    .from(schema.rawMaterials)
    .leftJoin(
      schema.rawMaterialStock,
      and(
        eq(schema.rawMaterialStock.rawMaterialId, schema.rawMaterials.id),
        eq(schema.rawMaterialStock.plantId, plantId)
      )
    )
    .orderBy(schema.rawMaterials.category, schema.rawMaterials.name);
  return rows.map((r) => ({
    ...r.material,
    qtyOnHand: r.stock?.qtyOnHand ?? 0,
    stockId: r.stock?.id ?? null,
  }));
}

export async function getLowStockItems(plantId: string) {
  const all = await getRawMaterialsWithStock(plantId);
  return all.filter(
    (m) => m.reorderPoint !== null && m.qtyOnHand < (m.reorderPoint ?? 0)
  );
}

export async function getFinishedGoodsWithStock(plantId: string) {
  const rows = await db
    .select({
      panel: schema.panelTypes,
      stock: schema.finishedGoodsStock,
    })
    .from(schema.panelTypes)
    .leftJoin(
      schema.finishedGoodsStock,
      and(
        eq(schema.finishedGoodsStock.panelTypeId, schema.panelTypes.id),
        eq(schema.finishedGoodsStock.plantId, plantId)
      )
    )
    .orderBy(
      schema.panelTypes.lengthFt,
      schema.panelTypes.railWeight,
      schema.panelTypes.skuCode
    );
  return rows.map((r) => ({
    ...r.panel,
    qtyOnHand: r.stock?.qtyOnHand ?? 0,
    stockId: r.stock?.id ?? null,
  }));
}

export async function getRecentBuilds(plantId: string, limit = 10) {
  return db
    .select({
      id: schema.buildEvents.id,
      qtyBuilt: schema.buildEvents.qtyBuilt,
      builtAt: schema.buildEvents.builtAt,
      railWasteFt: schema.buildEvents.railWasteFt,
      notes: schema.buildEvents.notes,
      panelSku: schema.panelTypes.skuCode,
      panelName: schema.panelTypes.displayName,
      userName: schema.users.name,
    })
    .from(schema.buildEvents)
    .innerJoin(
      schema.panelTypes,
      eq(schema.panelTypes.id, schema.buildEvents.panelTypeId)
    )
    .leftJoin(schema.users, eq(schema.users.id, schema.buildEvents.builtBy))
    .where(eq(schema.buildEvents.plantId, plantId))
    .orderBy(desc(schema.buildEvents.builtAt))
    .limit(limit);
}

export async function getRecentShipments(plantId: string, limit = 10) {
  return db
    .select({
      id: schema.shipmentEvents.id,
      qtyShipped: schema.shipmentEvents.qtyShipped,
      shippedAt: schema.shipmentEvents.shippedAt,
      customer: schema.shipmentEvents.customer,
      poNumber: schema.shipmentEvents.poNumber,
      panelSku: schema.panelTypes.skuCode,
      panelName: schema.panelTypes.displayName,
      userName: schema.users.name,
    })
    .from(schema.shipmentEvents)
    .innerJoin(
      schema.panelTypes,
      eq(schema.panelTypes.id, schema.shipmentEvents.panelTypeId)
    )
    .leftJoin(schema.users, eq(schema.users.id, schema.shipmentEvents.shippedBy))
    .where(eq(schema.shipmentEvents.plantId, plantId))
    .orderBy(desc(schema.shipmentEvents.shippedAt))
    .limit(limit);
}

export async function getBomForPanel(panelTypeId: string) {
  return db
    .select({
      line: schema.bomLines,
      material: schema.rawMaterials,
    })
    .from(schema.bomLines)
    .innerJoin(
      schema.rawMaterials,
      eq(schema.rawMaterials.id, schema.bomLines.rawMaterialId)
    )
    .where(eq(schema.bomLines.panelTypeId, panelTypeId))
    .orderBy(schema.rawMaterials.category, schema.rawMaterials.name);
}

export async function getLotsForMaterial(materialId: string, plantId: string) {
  return db
    .select()
    .from(schema.rawMaterialLots)
    .where(
      and(
        eq(schema.rawMaterialLots.rawMaterialId, materialId),
        eq(schema.rawMaterialLots.plantId, plantId)
      )
    )
    .orderBy(desc(schema.rawMaterialLots.receivedAt));
}

export async function getConsumptionForMaterial(
  materialId: string,
  plantId: string,
  limit = 30
) {
  return db
    .select({
      id: schema.buildEventConsumption.id,
      qtyConsumed: schema.buildEventConsumption.qtyConsumed,
      builtAt: schema.buildEvents.builtAt,
      qtyBuilt: schema.buildEvents.qtyBuilt,
      panelSku: schema.panelTypes.skuCode,
      panelName: schema.panelTypes.displayName,
    })
    .from(schema.buildEventConsumption)
    .innerJoin(
      schema.buildEvents,
      eq(schema.buildEvents.id, schema.buildEventConsumption.buildEventId)
    )
    .innerJoin(
      schema.panelTypes,
      eq(schema.panelTypes.id, schema.buildEvents.panelTypeId)
    )
    .where(
      and(
        eq(schema.buildEventConsumption.rawMaterialId, materialId),
        eq(schema.buildEvents.plantId, plantId)
      )
    )
    .orderBy(desc(schema.buildEvents.builtAt))
    .limit(limit);
}

export async function countFinishedOnHand(plantId: string) {
  const [row] = await db
    .select({
      total: sql<number>`COALESCE(SUM(${schema.finishedGoodsStock.qtyOnHand}), 0)`,
    })
    .from(schema.finishedGoodsStock)
    .where(eq(schema.finishedGoodsStock.plantId, plantId));
  return Number(row?.total ?? 0);
}

export async function getUsers() {
  return db
    .select()
    .from(schema.users)
    .orderBy(schema.users.name);
}

export async function getLotsNewestFirst(materialId: string, plantId: string) {
  return db
    .select()
    .from(schema.rawMaterialLots)
    .where(
      and(
        eq(schema.rawMaterialLots.rawMaterialId, materialId),
        eq(schema.rawMaterialLots.plantId, plantId),
        lt(sql`0`, schema.rawMaterialLots.qtyRemaining)
      )
    )
    .orderBy(schema.rawMaterialLots.receivedAt);
}
