import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_ROUTES = ["/login", "/signup", "/verify-email", "/welcome"];

export async function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  const isPublic = PUBLIC_ROUTES.some((r) => pathname.startsWith(r));

  // Check for Supabase auth cookie
  const hasAuthCookie = request.cookies
    .getAll()
    .some((c) => c.name.startsWith("sb-"));

  if (!hasAuthCookie && !isPublic) {
    const url = request.nextUrl.clone();
    // Site root: signed-out visitors get the marketing landing page (served
    // via rewrite so the URL stays "/") instead of being bounced to the
    // login form. Signed-in users keep seeing the dashboard at "/".
    if (pathname === "/") {
      url.pathname = "/welcome";
      return NextResponse.rewrite(url);
    }
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Node.js runtime (stable since Next.js 15.5): Vercel "services" does not
  // support Edge Function output, and this middleware does not need Edge.
  runtime: "nodejs",
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
