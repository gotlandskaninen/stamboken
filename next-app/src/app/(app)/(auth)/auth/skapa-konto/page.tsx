import { createHash } from "node:crypto";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { RichText } from "@payloadcms/richtext-lexical/react";
import { CreateAccount } from "@/components/auth/CodeLogin";
import styles from "@/components/auth/code-login.module.css";
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
  const { return_to } = await searchParams;
  // Each section shows either its CMS formatting, when that has the same
  // words as the hashed plain text, or the hashed plain text itself.
  return (
    <CreateAccount rules={displayed ?? undefined} returnTo={return_to}>
      {rules && (
        <section className={styles.rules} aria-labelledby="kontoregler">
          <h2 id="kontoregler">{rules.title}</h2>
          {rules.subtitle && <p>{rules.subtitle}</p>}
          {rules.sections.map(({ content, text }, index) =>
            content ? (
              <RichText
                key={index}
                data={content}
                disableContainer
                disableIndent
              />
            ) : (
              text
                ?.split("\n\n")
                .filter(Boolean)
                .map((paragraph, part) => (
                  <p key={`${index}-${part}`}>{paragraph}</p>
                ))
            ),
          )}
        </section>
      )}
    </CreateAccount>
  );
}
