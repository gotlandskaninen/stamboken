import type { Page } from "@playwright/test";

// Alla kaniner opens on status Aktiv; inactive seed rabbits (Visby Viking),
// Mellerud (no active seed rabbits) and more than one page need status Alla.
export async function showAllStatuses(page: Page) {
  await page
    .locator(".MuiFormControl-root", { hasText: "Status" })
    .locator(".MuiSelect-select")
    .click();
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes("/api/individuals") && !r.url().includes("status="),
    ),
    page.getByRole("option", { name: "Alla", exact: true }).click(),
  ]);
}
