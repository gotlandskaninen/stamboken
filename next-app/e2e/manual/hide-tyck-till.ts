import type { Page } from "@playwright/test";

// The Tyck till tab sits fixed on the right edge and covers buttons there, so
// a click waits for it forever. Hidden while the script clicks; screenshots.css
// shows it again for the picture, since it is part of every page.
export function hideTyckTillWhileClicking(page: Page) {
  return page.addInitScript(() => {
    const style = document.createElement("style");
    style.textContent =
      "[aria-label='Tyck till om sidan'] { visibility: hidden !important; }";
    document.addEventListener("DOMContentLoaded", () =>
      document.head.append(style),
    );
  });
}
