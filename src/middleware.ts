import { NextResponse, type NextRequest } from "next/server";
import { getIronSession } from "iron-session";
import type { SessionData } from "@/lib/session";

const PUBLIC_PATHS = [
  "/login",
  "/auth/verify",
  "/auth/sent",
  "/not-authorized",
];

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/cron") ||
    pathname.startsWith("/api/auth") ||
    pathname === "/favicon.ico" ||
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))
  ) {
    return NextResponse.next();
  }

  const secret = process.env.SESSION_SECRET;
  if (!secret || secret.length < 32) {
    // Let the page render a helpful error instead of crashing middleware.
    return NextResponse.next();
  }

  const res = NextResponse.next();
  const session = await getIronSession<SessionData>(req, res, {
    password: secret,
    cookieName: "omega_inventory_session",
  });

  if (!session.userId) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  if (pathname.startsWith("/admin") && session.role !== "admin") {
    const url = req.nextUrl.clone();
    url.pathname = "/not-authorized";
    return NextResponse.redirect(url);
  }

  if (pathname.startsWith("/log") && session.role !== "admin") {
    const url = req.nextUrl.clone();
    url.pathname = "/not-authorized";
    return NextResponse.redirect(url);
  }

  return res;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
