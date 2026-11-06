// Spec §7.3 password-reset: reset a user's password, assert plaintext shown
// once; navigate away and back — plaintext no longer present. §5.7: the
// generated password is 22 chars base64url (crypto.randomBytes(16)).
//
// NOTE: test-dual's password permanently changes each run (the panel only
// generates random passwords, by design). test-dual is not used by any
// other suite, and bootstrap re-creation is idempotent-skip — acceptable
// for the disposable local-production stack; documented here on purpose.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN, VICTIM_PASSWORD } from "./helpers/auth";
import {
  DONE_BUTTON,
  PASSWORD_RESET_HEADING,
  PASSWORD_RESET_ONCE,
  RESET_PASSWORD_BUTTON,
  SEARCH_FIELD,
} from "./helpers/copy";

const BASE64URL_22 = /[A-Za-z0-9_-]{22}/;

test("plaintext shows exactly once and the new password works", async ({
  page,
  context,
  request,
}) => {
  await loginAs(page, context, ADMIN, "prod");
  await page.goto("/stamboken/admin/anvandare");
  await page
    .getByRole("textbox", { name: SEARCH_FIELD })
    .fill(VICTIM_PASSWORD.username);
  await page
    .getByRole("link", { name: VICTIM_PASSWORD.username, exact: true })
    .click();
  const detailUrl = page.url();

  await page.getByRole("button", { name: RESET_PASSWORD_BUTTON }).click();

  // §5.7 one-time display block, verbatim copy anchors.
  await expect(page.getByText(PASSWORD_RESET_HEADING)).toBeVisible();
  await expect(page.getByText(PASSWORD_RESET_ONCE)).toBeVisible();
  const displayed = await page.locator("body").innerText();
  const match = displayed.match(BASE64URL_22);
  expect(match, "22-char base64url password must be displayed").toBeTruthy();
  const plaintext = match![0];

  // The new password actually works (isolated request context — does not
  // touch the admin's browser session).
  const login = await request.post("/api/login", {
    data: { username: VICTIM_PASSWORD.username, password: plaintext },
  });
  expect(login.ok()).toBeTruthy();

  // [Klar] → redirect to the user detail view (§5.7).
  await page.getByRole("button", { name: DONE_BUTTON }).click();
  await page.waitForURL(/\/stamboken\/admin\/anvandare\/\d+/);

  // Navigate away and back — plaintext is gone (shown exactly once).
  await page.goto("/stamboken/admin");
  await page.goto(detailUrl);
  expect(await page.locator("body").innerText()).not.toContain(plaintext);
});
