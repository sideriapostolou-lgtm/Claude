"use server";

import { db, schema } from "@/db";
import { and, eq, sql } from "drizzle-orm";
import { requireAdmin } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { z } from "zod";

const receiptSchema = z.object({
  rawMaterialId: z.string().uuid(),
  plantId: z.string().uuid(),
  lotNumber: z.string().min(1),
  vendor: z.string().optional(),
  poNumber: z.string().optional(),
  qtyReceived: z.number().int().positive(),
  receivedAt: z.string().datetime().or(z.string()).optional(),
  notes: z.string().optional(),
});

export async function logReceipt(input: z.infer<typeof receiptSchema>) {
  try {
    const user = await requireAdmin();
    const parsed = receiptSchema.safeParse(input);
    if (!parsed.success) {
      return { ok: false as const, error: parsed.error.issues[0]?.message };
    }
    const data = parsed.data;

    await db.transaction(async (tx) => {
      await tx.insert(schema.rawMaterialLots).values({
        rawMaterialId: data.rawMaterialId,
        plantId: data.plantId,
        lotNumber: data.lotNumber,
        vendor: data.vendor ?? null,
        poNumber: data.poNumber ?? null,
        qtyReceived: data.qtyReceived,
        qtyRemaining: data.qtyReceived,
        receivedAt: data.receivedAt ? new Date(data.receivedAt) : new Date(),
        receivedBy: user.id,
        notes: data.notes ?? null,
      });

      const [existing] = await tx
        .select()
        .from(schema.rawMaterialStock)
        .where(
          and(
            eq(schema.rawMaterialStock.rawMaterialId, data.rawMaterialId),
            eq(schema.rawMaterialStock.plantId, data.plantId)
          )
        );
      if (existing) {
        await tx
          .update(schema.rawMaterialStock)
          .set({
            qtyOnHand: sql`${schema.rawMaterialStock.qtyOnHand} + ${data.qtyReceived}`,
            lastUpdated: new Date(),
          })
          .where(eq(schema.rawMaterialStock.id, existing.id));
      } else {
        await tx.insert(schema.rawMaterialStock).values({
          rawMaterialId: data.rawMaterialId,
          plantId: data.plantId,
          qtyOnHand: data.qtyReceived,
        });
      }

      // Bubble the vendor onto the material if it was blank and we just saw one.
      if (data.vendor) {
        await tx
          .update(schema.rawMaterials)
          .set({ vendor: data.vendor })
          .where(
            and(
              eq(schema.rawMaterials.id, data.rawMaterialId),
              sql`${schema.rawMaterials.vendor} IS NULL OR ${schema.rawMaterials.vendor} = ''`
            )
          );
      }
    });

    revalidatePath("/");
    revalidatePath("/raw-materials");
    revalidatePath(`/raw-materials/${data.rawMaterialId}`);
    return { ok: true as const };
  } catch (err) {
    console.error("logReceipt failed", err);
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}
