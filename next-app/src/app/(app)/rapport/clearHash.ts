// Runs as an inline script while the HTML is parsed, before any application script: the token after # in the link
// leaves the address bar at once and waits in memory for LinkGate. (The app sets no CSP that forbids it; if one is
// added, this script needs a nonce.)
export const CLEAR_HASH_SCRIPT = `(function(){var h=location.hash;if(h){if(h.length>1)window.__rapportToken=h.slice(1);history.replaceState(null,"","/rapport");}})();`;

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
