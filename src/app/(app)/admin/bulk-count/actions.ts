"use server";

import { db, schema } from "@/db";
import { and, eq } from "drizzle-orm";
import { requireAdmin } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { z } from "zod";

const bulkSchema = z.object({
  plantId: z.string().uuid(),
  rawMaterials: z.array(
    z.object({ id: z.string().uuid(), qtyOnHand: z.number().int().min(0) })
  ),
  finishedGoods: z.array(
    z.object({ id: z.string().uuid(), qtyOnHand: z.number().int().min(0) })
  ),
});

export async function saveBulkCount(input: z.infer<typeof bulkSchema>) {
  try {
    await requireAdmin();
    const parsed = bulkSchema.safeParse(input);
    if (!parsed.success) {
      return { ok: false as const, error: parsed.error.issues[0]?.message };
    }
    const { plantId, rawMaterials, finishedGoods } = parsed.data;

    await db.transaction(async (tx) => {
      for (const rm of rawMaterials) {
        const [existing] = await tx
          .select()
          .from(schema.rawMaterialStock)
          .where(
            and(
              eq(schema.rawMaterialStock.rawMaterialId, rm.id),
              eq(schema.rawMaterialStock.plantId, plantId)
            )
          );
        if (existing) {
          await tx
            .update(schema.rawMaterialStock)
            .set({ qtyOnHand: rm.qtyOnHand, lastUpdated: new Date() })
            .where(eq(schema.rawMaterialStock.id, existing.id));
        } else {
          await tx.insert(schema.rawMaterialStock).values({
            rawMaterialId: rm.id,
            plantId,
            qtyOnHand: rm.qtyOnHand,
          });
        }
      }
      for (const fg of finishedGoods) {
        const [existing] = await tx
          .select()
          .from(schema.finishedGoodsStock)
          .where(
            and(
              eq(schema.finishedGoodsStock.panelTypeId, fg.id),
              eq(schema.finishedGoodsStock.plantId, plantId)
            )
          );
        if (existing) {
          await tx
            .update(schema.finishedGoodsStock)
            .set({ qtyOnHand: fg.qtyOnHand, lastUpdated: new Date() })
            .where(eq(schema.finishedGoodsStock.id, existing.id));
        } else {
          await tx.insert(schema.finishedGoodsStock).values({
            panelTypeId: fg.id,
            plantId,
            qtyOnHand: fg.qtyOnHand,
          });
        }
      }
    });

    revalidatePath("/");
    revalidatePath("/raw-materials");
    revalidatePath("/finished-goods");
    return {
      ok: true as const,
      count: rawMaterials.length + finishedGoods.length,
    };
  } catch (err) {
    console.error("saveBulkCount failed", err);
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}
