// Spec §7.3 admin-mode-gate: test-admin in demo mode gets the §1.1
// mode-switch prompt (full-page RSC render, no client redirect); clicking
// "Byt till riktiga stamboken" runs setMode('prod') — which re-validates
// v2_prod_access against the prod API (global-setup promoted test-admin) —
// and the panel renders.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import {
  MODE_PROMPT_BUTTON,
  MODE_PROMPT_HEADING,
  PANEL_HEADING,
  TAB_USERS,
} from "./helpers/copy";

test("demo mode renders mode-switch prompt; switching enters the panel", async ({
  page,
  context,
}) => {
  await loginAs(page, context, ADMIN, "demo");
  await page.goto("/stamboken/admin");
  await expect(page.getByText(MODE_PROMPT_HEADING)).toBeVisible();
  await expect(
    page.getByRole("button", { name: MODE_PROMPT_BUTTON }),
  ).toBeVisible();

  await page.getByRole("button", { name: MODE_PROMPT_BUTTON }).click();
  await expect(
    page.getByRole("heading", { name: PANEL_HEADING }),
  ).toBeVisible();
});

test("prod mode renders the panel directly (card grid)", async ({
  page,
  context,
}) => {
  await loginAs(page, context, ADMIN, "prod");
  await page.goto("/stamboken/admin");
  await expect(
    page.getByRole("heading", { name: PANEL_HEADING }),
  ).toBeVisible();
  // C8: sidomenyn är borta — Användare-fliken bevisar att flikraden
  // renderades för en administratör (§2.2-etiketten "Alla användare" finns
  // inte längre i DOM:en; kortet på landningssidan heter "Användare").
  await expect(
    page.getByRole("tab", { name: TAB_USERS, exact: true }),
  ).toBeVisible();
});
