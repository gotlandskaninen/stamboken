import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Skärmbilder av kodinloggningen till manualen (projektet "login" i
// playwright.manual-screenshots.config.ts): fältet för engångskoden, sidan för
// länken i mejlet och Skapa mitt konto. Kräver samma API som
// public-code-login.spec.ts (container test-api med kodinloggning, se
// fixtures/code_login.py) och kontoreglerna i test-CMS:et; workflowet
// manual-screenshots.yml startar båda.

// Straight to Next, as public-code-login.spec.ts: the code login is only
// known to work there, and the pictures are the same.
test.use({
  baseURL: "http://localhost:3000",
  viewport: { width: 1280, height: 800 },
});

function fixture(action: "seed" | "mail", email: string) {
  const result = execFileSync(
    "docker",
    ["exec", "-i", "test-api", "python3", "-", action, email],
    {
      input: readFileSync(
        new URL("../fixtures/code_login.py", import.meta.url),
      ),
      encoding: "utf8",
    },
  );
  return JSON.parse(result);
}

test("kodinloggning och Skapa mitt konto", async ({ page, context }) => {
  const email = `pw-code-${randomUUID().replaceAll("-", "")}@example.org`;
  fixture("seed", email);

  await page.goto("/auth/sign-in");
  await page.getByLabel("E-postadress i matrikeln").fill(email);
  await page.getByRole("button", { name: "Skicka kod" }).click();
  const code = page.getByLabel("Engångskod");
  await expect(code).toBeVisible();
  await expect(page).toHaveScreenshot("logga-in-kod-desktop.png");

  let mail!: { digits: string; fragment: string };
  await expect(() => {
    const queued = fixture("mail", email);
    if (!queued) throw new Error("Waiting for the code in the fixture outbox");
    mail = queued;
  }).toPass({ timeout: 10000 });

  // The link page shows the name without using the code.
  const link = await context.newPage();
  await link.goto("/auth/kod" + mail.fragment);
  await expect(
    link.getByRole("button", { name: "Logga in här" }),
  ).toBeVisible();
  await expect(link).toHaveScreenshot("logga-in-lank-desktop.png");
  await link.close();

  await code.fill(mail.digits);
  await page.getByRole("button", { name: "Logga in med kod" }).click();
  await expect(
    page.getByRole("button", { name: "Skapa mitt konto" }),
  ).toBeVisible();
  await expect(page).toHaveScreenshot("skapa-konto-desktop.png", {
    fullPage: true,
  });
});
