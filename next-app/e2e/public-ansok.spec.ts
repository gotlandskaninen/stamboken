import { test, expect } from "@playwright/test";

test("anonymous user submits a membership application", async ({ page }) => {
  await page.goto("/ansok");
  await expect(
    page.getByRole("heading", { name: /Ansök om medlemskap/i }),
  ).toBeVisible();

  await page.getByLabel(/Förnamn/i).fill("Playwright");
  await page.getByLabel(/Efternamn/i).fill("Tester");
  await page.getByLabel(/E-post/i).fill(`pw-${Date.now()}@example.com`);
  await page.getByLabel(/Postnummer/i).fill("62355");
  // Clicking the next field blurs postnummer, which is what formats it.
  await page.getByLabel(/Postort/i).click();
  await page.getByLabel(/Postort/i).fill("Visby");
  await page.getByLabel(/GDPR/i).check();

  await expect(page.getByLabel(/Postnummer/i)).toHaveValue("623 55");
  await page.getByRole("button", { name: /Skicka ansökan/i }).click();

  await expect(page.getByText(/Tack för din ansökan/i)).toBeVisible({
    timeout: 10_000,
  });
});
