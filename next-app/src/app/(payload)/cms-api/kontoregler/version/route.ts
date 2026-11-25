import { getAccountRules } from "@/lib/account-rules";

export const dynamic = "force-dynamic";

export async function GET() {
  const rules = await getAccountRules();
  // Flask archives exactly this version and text at acceptance.
  return Response.json(
    rules ? { version: rules.version, text: rules.text } : {},
    {
      status: rules ? 200 : 503,
      headers: { "Cache-Control": "no-store" },
    },
  );
}
