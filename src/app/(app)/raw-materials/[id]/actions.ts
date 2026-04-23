"use server";

import { db, schema } from "@/db";
import { eq } from "drizzle-orm";
import { requireAdmin } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { z } from "zod";

const updateSchema = z.object({
  reorderPoint: z
    .string()
    .transform((s) => (s === "" ? null : Number(s)))
    .refine((v) => v === null || (Number.isInteger(v) && v >= 0), "Integer ≥ 0"),
  reorderQty: z
    .string()
    .transform((s) => (s === "" ? null : Number(s)))
    .refine((v) => v === null || (Number.isInteger(v) && v >= 0), "Integer ≥ 0"),
  vendor: z.string().transform((s) => s.trim() || null),
  notes: z.string().transform((s) => s.trim() || null),
});

export async function updateRawMaterial(id: string, fd: FormData) {
  try {
    await requireAdmin();
    const parsed = updateSchema.safeParse({
      reorderPoint: fd.get("reorderPoint") ?? "",
      reorderQty: fd.get("reorderQty") ?? "",
      vendor: fd.get("vendor") ?? "",
      notes: fd.get("notes") ?? "",
    });
    if (!parsed.success) {
      return { ok: false as const, error: parsed.error.issues[0]?.message };
    }
    await db
      .update(schema.rawMaterials)
      .set(parsed.data)
      .where(eq(schema.rawMaterials.id, id));
    revalidatePath(`/raw-materials/${id}`);
    revalidatePath("/raw-materials");
    return { ok: true as const };
  } catch (err) {
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}
