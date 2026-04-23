// Idempotent seed. Safe to re-run: every insert is guarded by an existence check.
// Callable as a CLI (`pnpm db:seed`) or imported from /api/admin/init.

import { db, schema } from "./index";
import { eq } from "drizzle-orm";
import {
  PLANT,
  USERS,
  RAW_MATERIALS,
  RAW_MATERIAL_ON_HAND,
  FINISHED_ON_HAND,
} from "./seed-data";
import {
  ALL_LENGTHS,
  ALL_TYPES,
  ALL_WEIGHTS,
  calcBom,
  displayName,
  fastenerType,
  panelSku,
} from "./bom";

export async function runSeed(log: (msg: string) => void = console.log) {
  log("Seeding Omega Inventory…");

  // 1. Plant
  let [plant] = await db
    .select()
    .from(schema.plants)
    .where(eq(schema.plants.code, PLANT.code));
  if (!plant) {
    [plant] = await db.insert(schema.plants).values(PLANT).returning();
    log(`  plant: inserted ${plant.code}`);
  } else {
    log(`  plant: ${plant.code} already present`);
  }

  // 2. Users
  for (const u of USERS) {
    const [existing] = await db
      .select()
      .from(schema.users)
      .where(eq(schema.users.email, u.email));
    if (!existing) {
      await db.insert(schema.users).values({
        email: u.email,
        name: u.name,
        role: u.role,
        receiveAlerts: true,
      });
      log(`  user: inserted ${u.email} (${u.role})`);
    }
  }

  // 3. Raw materials
  for (const rm of RAW_MATERIALS) {
    const [existing] = await db
      .select()
      .from(schema.rawMaterials)
      .where(eq(schema.rawMaterials.name, rm.name));
    if (!existing) {
      await db.insert(schema.rawMaterials).values({
        name: rm.name,
        unit: rm.unit,
        category: rm.category,
        reorderPoint: rm.reorderPoint ?? null,
        buyAmerica: rm.buyAmerica ?? false,
      });
      log(`  raw_material: inserted ${rm.name}`);
    }
  }

  // Re-fetch with IDs
  const allRaw = await db.select().from(schema.rawMaterials);
  const rawByName = new Map(allRaw.map((r) => [r.name, r]));

  // 4. Raw material stock (initial on-hand per plant)
  for (const [name, qty] of Object.entries(RAW_MATERIAL_ON_HAND)) {
    const rm = rawByName.get(name);
    if (!rm) {
      log(`    skipping stock for unknown material: ${name}`);
      continue;
    }
    const [existing] = await db
      .select()
      .from(schema.rawMaterialStock)
      .where(eq(schema.rawMaterialStock.rawMaterialId, rm.id));
    if (!existing) {
      await db.insert(schema.rawMaterialStock).values({
        rawMaterialId: rm.id,
        plantId: plant.id,
        qtyOnHand: qty,
      });
    }
  }
  // Ensure every raw material has a stock row (even if 0)
  for (const rm of allRaw) {
    const [existing] = await db
      .select()
      .from(schema.rawMaterialStock)
      .where(eq(schema.rawMaterialStock.rawMaterialId, rm.id));
    if (!existing) {
      await db.insert(schema.rawMaterialStock).values({
        rawMaterialId: rm.id,
        plantId: plant.id,
        qtyOnHand: 0,
      });
    }
  }

  // 5. Panel types (36 combos)
  for (const length of ALL_LENGTHS) {
    for (const type of ALL_TYPES) {
      for (const weight of ALL_WEIGHTS) {
        const sku = panelSku(length, type, weight);
        const [existing] = await db
          .select()
          .from(schema.panelTypes)
          .where(eq(schema.panelTypes.skuCode, sku));
        if (!existing) {
          await db.insert(schema.panelTypes).values({
            skuCode: sku,
            lengthFt: length,
            plateType: type[0] === "S" ? "Standard" : "Pandrol",
            tieType: type[1] === "E" ? `8'6" standard` : `10' switch`,
            railWeight: weight,
            fastenerType: fastenerType(type),
            displayName: displayName(length, type, weight),
          });
        }
      }
    }
  }

  const allPanels = await db.select().from(schema.panelTypes);
  const panelBySku = new Map(allPanels.map((p) => [p.skuCode, p]));

  // 6. BOM lines
  for (const length of ALL_LENGTHS) {
    for (const type of ALL_TYPES) {
      for (const weight of ALL_WEIGHTS) {
        const sku = panelSku(length, type, weight);
        const panel = panelBySku.get(sku);
        if (!panel) continue;
        const lines = calcBom(length, type, weight);
        for (const line of lines) {
          const rm = rawByName.get(line.material);
          if (!rm) {
            log(`    BOM: missing material ${line.material} for ${sku}`);
            continue;
          }
          const [existing] = await db
            .select()
            .from(schema.bomLines)
            .where(eq(schema.bomLines.panelTypeId, panel.id));
          const alreadyHasMaterial = (
            await db
              .select()
              .from(schema.bomLines)
              .where(eq(schema.bomLines.panelTypeId, panel.id))
          ).some((l) => l.rawMaterialId === rm.id);
          if (alreadyHasMaterial) continue;
          await db.insert(schema.bomLines).values({
            panelTypeId: panel.id,
            rawMaterialId: rm.id,
            qtyPerPanel: line.qty,
          });
        }
      }
    }
  }

  // 7. Finished goods stock
  for (const panel of allPanels) {
    const [existing] = await db
      .select()
      .from(schema.finishedGoodsStock)
      .where(eq(schema.finishedGoodsStock.panelTypeId, panel.id));
    if (!existing) {
      const qty = FINISHED_ON_HAND[panel.skuCode] ?? 0;
      await db.insert(schema.finishedGoodsStock).values({
        panelTypeId: panel.id,
        plantId: plant.id,
        qtyOnHand: qty,
      });
    }
  }

  log("Seed complete.");
}
