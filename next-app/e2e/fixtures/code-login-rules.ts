import { getPayload } from "payload";
import config from "../../src/payload.config";

// The Playwright job starts with an empty CMS database.
const db = new URL(process.env.CMS_DATABASE_URL ?? "");
if (
  process.env.GITHUB_ACTIONS !== "true" ||
  db.host !== "localhost:5433" ||
  db.pathname !== "/herdbook_cms"
) {
  throw new Error("Expected the isolated Playwright CMS");
}
const payload = await getPayload({ config });
try {
  await payload.create({
    collection: "pages",
    draft: false,
    data: {
      slug: "kontoregler",
      title: "Kontoregler för webbläsartestet",
      subtitle: "Använd bara testuppgifter.",
      layout: [{ blockType: "divider" }],
      _status: "published",
    },
  });
} finally {
  await payload.destroy();
}
