import { test as setup } from "@playwright/test";
import { loginAndSaveState } from "../e2e-shared/auth";

setup("authenticate as owner", async ({ page, context }) => {
  await loginAndSaveState(page, context, "owner", "e2e/.auth/gk-owner.json");
});

setup("authenticate as admin", async ({ page, context }) => {
  await loginAndSaveState(page, context, "admin", "e2e/.auth/admin.json");
});

setup("authenticate as manager", async ({ page, context }) => {
  await loginAndSaveState(
    page,
    context,
    "manager",
    "e2e/.auth/gk-manager.json",
  );
});
