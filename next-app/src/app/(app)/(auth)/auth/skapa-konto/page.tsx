import { createHash } from "node:crypto";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { CreateAccount } from "@/components/auth/CodeLogin";
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
  const displayed = rules && {
    version: rules.version,
    sha256: createHash("sha256").update(rules.text, "utf8").digest("hex"),
  };
  const [title, ...paragraphs] = rules?.text.split("\n\n") ?? [];
  const { return_to } = await searchParams;
  return (
    <CreateAccount rules={displayed ?? undefined} returnTo={return_to}>
      {rules && (
        <section style={{ whiteSpace: "pre-wrap" }}>
          <h2>{title}</h2>
          {paragraphs.map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </section>
      )}
    </CreateAccount>
  );
}
