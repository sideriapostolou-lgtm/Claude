import { NextRequest, NextResponse } from "next/server";
import { db, schema } from "@/db";
import { eq } from "drizzle-orm";
import { hashToken } from "@/lib/tokens";
import { getSession } from "@/lib/session";

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get("token");
  const next = req.nextUrl.searchParams.get("next") ?? "/";

  if (!token) {
    return NextResponse.redirect(new URL("/login?error=missing", req.url));
  }

  const hash = hashToken(token);
  const [record] = await db
    .select()
    .from(schema.loginTokens)
    .where(eq(schema.loginTokens.tokenHash, hash));

  if (!record) {
    return NextResponse.redirect(new URL("/login?error=invalid", req.url));
  }
  if (record.consumedAt) {
    return NextResponse.redirect(new URL("/login?error=used", req.url));
  }
  if (record.expiresAt.getTime() < Date.now()) {
    return NextResponse.redirect(new URL("/login?error=expired", req.url));
  }

  const [user] = await db
    .select()
    .from(schema.users)
    .where(eq(schema.users.id, record.userId));

  if (!user || !user.active) {
    return NextResponse.redirect(new URL("/not-authorized", req.url));
  }

  await db
    .update(schema.loginTokens)
    .set({ consumedAt: new Date() })
    .where(eq(schema.loginTokens.id, record.id));

  const session = await getSession();
  session.userId = user.id;
  session.email = user.email;
  session.name = user.name;
  session.role = user.role as "admin" | "viewer" | "operator";
  await session.save();

  const target = next.startsWith("/") ? next : "/";
  return NextResponse.redirect(new URL(target, req.url));
}
