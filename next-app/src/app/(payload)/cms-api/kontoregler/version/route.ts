import { getAccountRules } from "@/lib/account-rules";

export const dynamic = "force-dynamic";

export async function GET() {
  const rules = await getAccountRules();
  return Response.json(rules ?? {}, {
    status: rules ? 200 : 503,
    headers: { "Cache-Control": "no-store" },
  });
}
