import { test as setup } from "@playwright/test";
import { TEST_USERS, loginAndSaveState } from "./helpers/legacy-auth";

setup("authenticate test-admin", async ({ page, context }) => {
  await loginAndSaveState(page, context, TEST_USERS.admin, ".auth/admin.json");
});

setup("authenticate test-gk-owner", async ({ page, context }) => {
  await loginAndSaveState(
    page,
    context,
    TEST_USERS.gkOwner,
    ".auth/gk-owner.json",
  );
});

setup("authenticate test-gk-manager", async ({ page, context }) => {
  await loginAndSaveState(
    page,
    context,
    TEST_USERS.gkManager,
    ".auth/gk-manager.json",
  );
});
