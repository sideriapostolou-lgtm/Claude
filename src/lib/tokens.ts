import "server-only";
import { randomBytes, createHash } from "crypto";

const TOKEN_BYTES = 32;

export function generateToken(): { token: string; hash: string } {
  const token = randomBytes(TOKEN_BYTES).toString("base64url");
  return { token, hash: hashToken(token) };
}

export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export const LOGIN_TOKEN_TTL_MINUTES = 15;

export function loginTokenExpiry(): Date {
  return new Date(Date.now() + LOGIN_TOKEN_TTL_MINUTES * 60 * 1000);
}
