import { type Page } from "@playwright/test";

/**
 * Dismiss the cookie consent banner if it appears.
 * The legacy UI shows a banner with an "Okej! Jag forstar!" button.
 */
export async function dismissCookieBanner(page: Page): Promise<void> {
  const btn = page.getByRole("button", { name: /Okej/i });
  if (await btn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await btn.click();
  }
}
