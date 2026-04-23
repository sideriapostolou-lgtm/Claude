"use server";

import { db, schema } from "@/db";
import { eq } from "drizzle-orm";
import { requireAdmin } from "@/lib/session";
import { revalidatePath } from "next/cache";
import { z } from "zod";

const newUserSchema = z.object({
  email: z.string().email().toLowerCase(),
  name: z.string().min(1),
  role: z.enum(["admin", "viewer", "operator"]),
  receiveAlerts: z.boolean().default(true),
});

export async function addUser(input: z.infer<typeof newUserSchema>) {
  try {
    await requireAdmin();
    const parsed = newUserSchema.safeParse(input);
    if (!parsed.success) {
      return { ok: false as const, error: parsed.error.issues[0]?.message };
    }
    const [existing] = await db
      .select()
      .from(schema.users)
      .where(eq(schema.users.email, parsed.data.email));
    if (existing) {
      return { ok: false as const, error: "A user with that email already exists" };
    }
    await db.insert(schema.users).values(parsed.data);
    revalidatePath("/admin/users");
    return { ok: true as const };
  } catch (err) {
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}

const updateSchema = z.object({
  role: z.enum(["admin", "viewer", "operator"]),
  active: z.boolean(),
  receiveAlerts: z.boolean(),
});

export async function updateUser(
  id: string,
  input: z.infer<typeof updateSchema>
) {
  try {
    await requireAdmin();
    const parsed = updateSchema.safeParse(input);
    if (!parsed.success) {
      return { ok: false as const, error: parsed.error.issues[0]?.message };
    }
    await db
      .update(schema.users)
      .set(parsed.data)
      .where(eq(schema.users.id, id));
    revalidatePath("/admin/users");
    return { ok: true as const };
  } catch (err) {
    return {
      ok: false as const,
      error: err instanceof Error ? err.message : "Failed",
    };
  }
}
