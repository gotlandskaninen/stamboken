import { LoginLink } from "@/components/auth/CodeLogin";
import { codeLoginEnabled } from "@/lib/code-login-enabled";

export const metadata = {
  title: "Logga in med länk",
  robots: { index: false },
};

export default async function LoginLinkPage() {
  return <LoginLink enabled={await codeLoginEnabled()} />;
}
