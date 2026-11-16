// Runs as an inline script first in the root layout's <head>: the earliest point the app controls. (React hoists the
// framework's async chunk <script src> tags above it and no layout code can go before them; they only run after the
// first HTML chunk has been parsed, which holds this script. The e2e checks the order in the served HTML.) It acts only
// on /rapport, and also listens for hash changes, so a link opened before the app has started is taken out of the
// address bar and kept in memory too (Next's own hydration may rewrite the address).
export const CLEAR_HASH_SCRIPT = `(function(){function t(){var h=location.hash;if(h&&location.pathname==="/rapport"){if(h.length>1)window.__rapportToken=h.slice(1);history.replaceState(null,"","/rapport");}}t();window.addEventListener("hashchange",t);})();`;

// The token waiting in memory, or one still in the address bar (the script did not run, or a link was opened inside the
// open page); the address bar is cleared either way.
export function takeToken(): string {
  const w = window as unknown as { __rapportToken?: string };
  let token = w.__rapportToken ?? "";
  delete w.__rapportToken;
  if (location.hash) {
    token = location.hash.slice(1) || token;
    history.replaceState(null, "", "/rapport");
  }
  return token;
}
