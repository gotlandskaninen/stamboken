// Runs as an inline script, the first inline script in the root layout's <head>, so the hash is cleared before the
// app's own code (hydration, LinkGate) runs. It is not guaranteed to run before the framework's async chunks, which
// React hoists above it (a slow stylesheet can let one of them run first); no sink that records the address is known
// there. It acts only on /rapport, and also listens for hash changes, so a link opened before the app has started is
// taken out of the address bar and kept in memory too (Next's own hydration may rewrite the address).
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
