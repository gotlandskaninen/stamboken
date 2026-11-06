// Spec §7.3 inaktivera-konto (rev 10 B1): deactivate a test user; assert
// the red "Kontot är inaktiverat" banner, the Inaktiv filter finds them,
// and (API-level) their login now fails; reactivate. §4.12 semantics.
// Uses the isolated `request` fixture for the victim's login attempts so
// the admin's browser session is never clobbered.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN, VICTIM_DEACTIVATE } from "./helpers/auth";
import {
  ACTIVE_TOGGLE,
  CONFIRM_BUTTON,
  DEACTIVATED_BANNER,
  INACTIVE_FILTER,
  SEARCH_FIELD,
} from "./helpers/copy";

test("deactivate blocks login, shows banner + filter; reactivate restores", async ({
  page,
  context,
  request,
}) => {
  await loginAs(page, context, ADMIN, "prod");

  // Precondition: the victim can log in.
  const before = await request.post("/api/login", { data: VICTIM_DEACTIVATE });
  expect(before.ok()).toBeTruthy();

  // Deactivate via the detail-page toggle + ConfirmDialog (Task 26).
  await page.goto("/stamboken/admin/anvandare");
  await page
    .getByRole("textbox", { name: SEARCH_FIELD })
    .fill(VICTIM_DEACTIVATE.username);
  await page
    .getByRole("link", { name: VICTIM_DEACTIVATE.username, exact: true })
    .click();
  // Wait out the search-rerender/navigation race before reading the URL.
  await expect(page).toHaveURL(/\/stamboken\/admin\/anvandare\/\d+/);
  const detailUrl = page.url();
  await page.getByRole("switch", { name: ACTIVE_TOGGLE }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: CONFIRM_BUTTON })
    .click();

  // Red banner on the detail page (§4.12 UI).
  await page.goto(detailUrl);
  await expect(page.getByText(DEACTIVATED_BANNER)).toBeVisible();

  // Inaktiv list filter finds the account (§3.1).
  await page.goto("/stamboken/admin/anvandare?active=false");
  // Anchor on the victim's own grid row: the username link identifies it and
  // the Inaktiv status badge must live inside that same row (C11 grid).
  const victimRow = page.getByRole("row").filter({
    has: page.getByRole("link", {
      name: VICTIM_DEACTIVATE.username,
      exact: true,
    }),
  });
  await expect(victimRow).toBeVisible();
  await expect(
    victimRow.getByText(INACTIVE_FILTER, { exact: true }),
  ).toBeVisible();

  // API-level: password login is now rejected (§4.12 layer 1).
  const blocked = await request.post("/api/login", { data: VICTIM_DEACTIVATE });
  expect(blocked.ok()).toBeFalsy();

  // Reactivate + verify login works again.
  await page.goto(detailUrl);
  await page.getByRole("switch", { name: ACTIVE_TOGGLE }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: CONFIRM_BUTTON })
    .click();
  // The Server Action + revalidate run async after the confirm click —
  // wait until the reloaded detail page drops the banner before the login
  // attempt, or the POST races the write (flaked on local-production).
  await page.goto(detailUrl);
  await expect(page.getByText(DEACTIVATED_BANNER)).toHaveCount(0);
  const after = await request.post("/api/login", { data: VICTIM_DEACTIVATE });
  expect(after.ok()).toBeTruthy();
});
