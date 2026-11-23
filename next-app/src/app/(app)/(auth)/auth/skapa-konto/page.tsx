import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { CreateAccount } from "@/components/auth/CodeLogin";
import { RenderBlocks } from "@/components/blocks/RenderBlocks";
import { getAccountRules } from "@/lib/account-rules";
import { codeLoginEnabled } from "@/lib/code-login-enabled";

export const metadata = { title: "Skapa mitt konto", robots: { index: false } };

export default async function CreateAccountPage({
  searchParams,
}: {
  searchParams: Promise<{ return_to?: string }>;
}) {
  if (!(await cookies()).has("session") || !(await codeLoginEnabled()))
    redirect("/auth/sign-in");
  const rules = await getAccountRules();
  const { return_to } = await searchParams;
  return (
    <CreateAccount version={rules?.version} returnTo={return_to}>
      {rules && (
        <section>
          <h2>{rules.page.title}</h2>
          {rules.page.subtitle && <p>{rules.page.subtitle}</p>}
          <RenderBlocks blocks={rules.page.layout!} />
        </section>
      )}
    </CreateAccount>
  );
}
