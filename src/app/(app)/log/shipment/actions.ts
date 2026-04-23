"use server";

import { db, schema } from "@/db";
import { and, eq, sql } from "drizzle-orm";
import { requireAdmin } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { z } from "zod";

const shipmentSchema = z.object({
  panelTypeId: z.string().uuid(),
  plantId: z.string().uuid(),
  qtyShipped: z.number().int().positive(),
  customer: z.string().default("BNSF"),
  poNumber: z.string().optional(),
  notes: z.string().optional(),
});

export async function logShipment(input: z.infer<typeof shipmentSchema>) {
  try {
    const user = await requireAdmin();
    const parsed = shipmentSchema.safeParse(input);
    if (!parsed.success) {
      return { ok: false as const, error: parsed.error.issues[0]?.message };
    }
    const { panelTypeId, plantId, qtyShipped, customer, poNumber, notes } =
      parsed.data;

    const [stock] = await db
      .select()
      .from(schema.finishedGoodsStock)
      .where(
        and(
          eq(schema.finishedGoodsStock.panelTypeId, panelTypeId),
          eq(schema.finishedGoodsStock.plantId, plantId)
        )
      );
    if (!stock || stock.qtyOnHand < qtyShipped) {
      return { ok: false as const, error: "Not enough on hand to ship" };
    }

    await db.transaction(async (tx) => {
      await tx.insert(schema.shipmentEvents).values({
        panelTypeId,
        plantId,
        qtyShipped,
        customer,
        poNumber: poNumber ?? null,
        notes: notes ?? null,
        shippedBy: user.id,
      });
      await tx
        .update(schema.finishedGoodsStock)
        .set({
          qtyOnHand: sql`${schema.finishedGoodsStock.qtyOnHand} - ${qtyShipped}`,
          lastUpdated: new Date(),
        })
        .where(eq(schema.finishedGoodsStock.id, stock.id));
    });

    revalidatePath("/");
    revalidatePath("/finished-goods");
    revalidatePath(`/finished-goods/${panelTypeId}`);
    return { ok: true as const };
  } catch (err) {
    console.error("logShipment failed", err);
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}
