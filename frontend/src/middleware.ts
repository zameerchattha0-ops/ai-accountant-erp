import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_ROUTES = [
  "/login",
  "/signup",
  "/verify-email",
  "/auth",
  "/welcome",
  // Marketing pages linked from the header — accessible to everyone
  "/features",
  "/how-it-works",
  "/solutions",
  "/pricing",
  "/resources",
];

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
    // Skip internal assets, the 3D model directory, and ALL static file
    // extensions — otherwise asset requests (e.g. /models/*.glb) get treated
    // as page navigations and redirected to /login, which serves HTML where
    // loaders expect binary/JSON and crashes the client.
    "/((?!_next/static|_next/image|favicon.ico|models/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|avif|glb|gltf|ico|txt|json|xml|webmanifest|mp4|webm|mov|mp3|wav|ogg|woff|woff2|ttf|otf|eot|wasm|bin|hdr|ktx2)$).*)",
  ],
};
