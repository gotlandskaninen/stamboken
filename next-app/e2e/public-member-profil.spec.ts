import { test, expect } from "@playwright/test";

test("linked member can toggle Koharen publication consent", async ({
  page,
}) => {
  await page.request.post("/api/login", {
    data: { username: "test-member", password: "test-member-pass" },
    headers: { "Content-Type": "application/json" },
  });

  await page.goto("/stamboken/profil");
  await expect(page.getByRole("heading", { name: "Min profil" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Publicering i Koharen" }),
  ).toBeVisible();

  // Scoped to the Koharen card — "E-post" also labels the Kontakt input.
  const koharen = page.locator("section", {
    has: page.getByRole("heading", { name: "Publicering i Koharen" }),
  });
  const toggle = koharen.getByLabel("E-post", { exact: true });
  const before = await toggle.isChecked();
  await toggle.click();
  await koharen.getByRole("button", { name: "Spara", exact: true }).click();
  await expect(page.getByText("Publiceringsval sparade")).toBeVisible();

  await page.reload();
  expect(await koharen.getByLabel("E-post", { exact: true }).isChecked()).toBe(
    !before,
  );
});

test("the old member profile URL is gone", async ({ page }) => {
  await page.request.post("/api/login", {
    data: { username: "test-member", password: "test-member-pass" },
    headers: { "Content-Type": "application/json" },
  });
  const res = await page.goto("/medlem/profil");
  expect(res?.status()).toBe(404);
});
