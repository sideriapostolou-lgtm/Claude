import "server-only";
import { cookies } from "next/headers";
import { getIronSession, type SessionOptions } from "iron-session";
import { cache } from "react";

export interface SessionData {
  userId?: string;
  email?: string;
  role?: "admin" | "viewer" | "operator";
  name?: string;
}

const SESSION_COOKIE = "omega_inventory_session";

function sessionOptions(): SessionOptions {
  const secret = process.env.SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error(
      "SESSION_SECRET must be set and at least 32 characters (use `openssl rand -hex 32`)"
    );
  }
  return {
    password: secret,
    cookieName: SESSION_COOKIE,
    cookieOptions: {
      secure: process.env.NODE_ENV === "production",
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30, // 30 days rolling
    },
  };
}

export async function getSession() {
  return getIronSession<SessionData>(cookies(), sessionOptions());
}

export const getCurrentUser = cache(async () => {
  const session = await getSession();
  if (!session.userId || !session.email || !session.role) return null;
  return {
    id: session.userId,
    email: session.email,
    role: session.role,
    name: session.name ?? session.email,
  };
});

export async function requireUser() {
  const user = await getCurrentUser();
  if (!user) throw new Error("Unauthorized");
  return user;
}

export async function requireAdmin() {
  const user = await requireUser();
  if (user.role !== "admin") throw new Error("Forbidden: admin only");
  return user;
}
