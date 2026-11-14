// Whether a menu link points at the page being shown. Links come from the
// CMS, so "/historik/" and "/historik?x=1" must match "/historik"; anything
// that is not a site path (mailto:, another site) never matches.
export function isCurrentPath(pathname: string, href: string): boolean {
  if (!href.startsWith("/")) return false;
  const path = href.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
  return path === (pathname.replace(/\/+$/, "") || "/");
}
