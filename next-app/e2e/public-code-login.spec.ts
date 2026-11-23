import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import sharp from "sharp";

// Opt in on the CI-style local test-api with a test LINK_SECRET, log-only mail,
// KODINLOGGNING=true, SJALVSKAPAT_KONTO_PROD=true and NEXT_INTERNAL_ORIGIN
// pointing to this Next server. Its test CMS needs published kontoregler content.
test.skip(
  process.env.E2E_CODE_LOGIN !== "1",
  "Requires the code-login fixture stack",
);
test.use({
  viewport: { width: 375, height: 812 },
  hasTouch: true,
  trace: "off",
  screenshot: "off",
});

function fixture(action: "seed", email: string): string;
function fixture(
  action: "mail",
  email: string,
): { digits: string; fragment: string } | null;
function fixture(action: string, email: string) {
  const result = execFileSync(
    "docker",
    ["exec", "-i", "test-api", "python3", "-", action, email],
    {
      input: readFileSync(new URL("fixtures/code_login.py", import.meta.url)),
      encoding: "utf8",
    },
  );
  return JSON.parse(result);
}

test("a member signs in by code, accepts the rules and uploads a certificate on a phone", async ({
  page,
  context,
  baseURL,
}) => {
  test.setTimeout(120_000);
  expect(baseURL).toBe("http://localhost:3000");
  const email = `pw-code-${randomUUID().replaceAll("-", "")}@example.org`;
  const herd = fixture("seed", email);
  await page.goto("/auth/sign-in?return_to=%2Fstamboken%2Finskick%2Fny");
  await page.getByLabel("E-postadress i matrikeln").fill(email);
  await page.getByRole("button", { name: "Skicka kod" }).click();
  const code = page.getByLabel("Engångskod");
  await expect(code).toHaveAttribute("inputmode", "numeric");
  await expect(code).toHaveAttribute("autocomplete", "one-time-code");
  // The API has already replied when it starts filling the outbox.
  let mail!: { digits: string; fragment: string };
  await expect(() => {
    const queued = fixture("mail", email);
    if (!queued) throw new Error("Waiting for the code in the fixture outbox");
    mail = queued;
  }).toPass({ timeout: 10000 });
  const { digits, fragment } = mail;

  // Following the mail in a second tab can show the name without consuming the code.
  const linkPage = await context.newPage();
  await linkPage.goto("/auth/kod" + fragment);
  await expect(linkPage.getByText(/Kodtest Mobil/)).toBeVisible();
  await expect(
    linkPage.getByRole("button", { name: "Logga in här" }),
  ).toBeVisible();
  await expect(linkPage).toHaveURL(/\/auth\/kod$/);
  await linkPage.goto("/auth/sign-in");
  await linkPage.goBack();
  await expect(linkPage).toHaveURL(/\/auth\/kod$/);
  await linkPage.close();

  await code.fill(digits);
  await page.getByRole("button", { name: "Logga in med kod" }).click();
  const create = page.getByRole("button", { name: "Skapa mitt konto" });
  await expect(create).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "Jag har läst reglerna och följer dem." })
    .check();
  await create.click();
  await expect(
    page.getByRole("heading", { name: "Ladda upp intyg" }),
  ).toBeVisible();
  await expect(page.getByLabel("Besättning", { exact: true })).toHaveValue(
    herd,
  );

  const photo = await sharp({
    create: { width: 40, height: 40, channels: 3, background: "white" },
  })
    .png()
    .toBuffer();
  await page.getByTestId("inskick-files").setInputFiles({
    name: "kodtest.png",
    mimeType: "image/png",
    buffer: photo,
  });
  await page.getByRole("button", { name: "Skicka", exact: true }).click();
  await page.getByRole("button", { name: "Skicka ändå" }).click();
  await expect(page).toHaveURL(/\/stamboken\/inskick#arende-\d+$/);
  await expect(page.locator(new URL(page.url()).hash)).toContainText(
    "Mottaget",
  );
});
