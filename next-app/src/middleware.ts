import { NextRequest, NextResponse } from "next/server";

/**
 * Routes that require a Stamboken (Flask) session: the herdbook dashboard and
 * the Payload CMS admin. Unauthenticated visits go to the single sign-in page.
 */
export function middleware(request: NextRequest) {
  const sessionCookie = request.cookies.get("session");
  const currentPath = request.nextUrl.pathname + request.nextUrl.search;
  if (!sessionCookie) {
    const returnTo = encodeURIComponent(currentPath);
    return NextResponse.redirect(
      new URL(`/auth/sign-in?return_to=${returnTo}`, request.url),
    );
  }
  // Expose the path so server components (requireUser) can preserve destination.
  const response = NextResponse.next();
  response.headers.set("x-next-url", currentPath);
  return response;
}

export const config = {
  // Protect /stamboken/*, /admin (and /admin/*), and /medlem/*. Exclude paths
  // containing a dot (static assets), Payload's own API/asset routes under
  // /admin, and the public certificate verification pages
  // (/stamboken/verifiera/* — QR landing).
  matcher: [
    "/stamboken/((?!verifiera(?:/|$))(?!.*\\.).*)",
    "/admin/:path*",
    "/medlem/((?!.*\\.).*)",
  ],
};
