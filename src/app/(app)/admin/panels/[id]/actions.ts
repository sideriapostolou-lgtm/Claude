"use server";

import { db, schema } from "@/db";
import { eq } from "drizzle-orm";
import { requireAdmin } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { z } from "zod";

const panelSchema = z.object({
  displayName: z.string().min(1),
  active: z.boolean(),
});

export async function updatePanel(
  id: string,
  input: z.infer<typeof panelSchema>
) {
  try {
    await requireAdmin();
    const parsed = panelSchema.safeParse(input);
    if (!parsed.success)
      return { ok: false as const, error: parsed.error.issues[0]?.message };
    await db
      .update(schema.panelTypes)
      .set(parsed.data)
      .where(eq(schema.panelTypes.id, id));
    revalidatePath(`/admin/panels/${id}`);
    revalidatePath("/admin/panels");
    revalidatePath(`/finished-goods/${id}`);
    return { ok: true as const };
  } catch (err) {
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}

export async function updateBomLine(lineId: string, qtyPerPanel: number) {
  try {
    await requireAdmin();
    if (!Number.isInteger(qtyPerPanel) || qtyPerPanel < 0) {
      return { ok: false as const, error: "Quantity must be a non-negative integer" };
    }
    await db
      .update(schema.bomLines)
      .set({ qtyPerPanel })
      .where(eq(schema.bomLines.id, lineId));
    revalidatePath("/admin/panels");
    return { ok: true as const };
  } catch (err) {
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}
