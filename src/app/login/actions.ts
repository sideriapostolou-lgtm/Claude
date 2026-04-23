"use server";

import { db, schema } from "@/db";
import { eq, and } from "drizzle-orm";
import { generateToken, loginTokenExpiry, LOGIN_TOKEN_TTL_MINUTES } from "@/lib/tokens";
import { sendEmail, magicLinkEmailTemplate } from "@/lib/email";
import { z } from "zod";

const emailSchema = z.string().email().toLowerCase();

function appUrl() {
  const u = process.env.NEXT_PUBLIC_APP_URL;
  if (!u) throw new Error("NEXT_PUBLIC_APP_URL is not set");
  return u.replace(/\/$/, "");
}

export async function requestLoginLink(
  email: string,
  next?: string
): Promise<{ ok: boolean; error?: string }> {
  const parsed = emailSchema.safeParse(email);
  if (!parsed.success) {
    return { ok: false, error: "Please enter a valid email address" };
  }

  // Always show a success-ish response to avoid email enumeration. Only send
  // the actual email if the user exists and is active.
  const [user] = await db
    .select()
    .from(schema.users)
    .where(and(eq(schema.users.email, parsed.data), eq(schema.users.active, true)));

  if (!user) {
    // Small delay parity so enumeration timing is harder.
    await new Promise((r) => setTimeout(r, 250));
    return { ok: true };
  }

  const { token, hash } = generateToken();
  await db.insert(schema.loginTokens).values({
    userId: user.id,
    tokenHash: hash,
    expiresAt: loginTokenExpiry(),
  });

  const url = new URL(`${appUrl()}/auth/verify`);
  url.searchParams.set("token", token);
  if (next && next.startsWith("/")) url.searchParams.set("next", next);

  const { subject, html, text } = magicLinkEmailTemplate({
    name: user.name,
    url: url.toString(),
    expiresInMinutes: LOGIN_TOKEN_TTL_MINUTES,
  });

  try {
    await sendEmail({ to: user.email, subject, html, text });
  } catch (err) {
    console.error("sendEmail failed", err);
    return { ok: false, error: "Could not send the login email. Try again shortly." };
  }

  return { ok: true };
}
