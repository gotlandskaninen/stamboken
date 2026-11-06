import { cookies } from "next/headers";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getUser } from "@/lib/auth";
import { fetchApi } from "@/lib/api";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import { setMode } from "@/app/(app)/(auth)/actions";
import { AdminTabs } from "./_components/AdminTabs";
import { adminRoleLine, hasAnyVisible } from "./_components/navConfig";
import ds from "@/styles/ds-admin.module.css";
import styles from "./admin.module.css";

type GenebankShort = { id: number; name: string };

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 1. Mode gate: full-page RSC prompt, never a client redirect.
  //    Copy matches Phase 999.2 language.
  const cookieStore = await cookies();
  const mode = parseMode(cookieStore.get(MODE_COOKIE)?.value);
  if (mode !== "prod") {
    return (
      <div className={`${styles["ad-container"]} ${styles["ad-main"]}`}>
        <div className={`sb-card ${styles["ad-prompt"]}`}>
          <h1 className={`sb-h4 ${styles["ad-prompt-title"]}`}>
            Adminpanelen finns i den riktiga stamboken.
          </h1>
          <p className={ds["ad-hint"]}>
            Du använder just nu demoversionen. Byt till den riktiga stamboken
            för att öppna adminpanelen.
          </p>
          <div className={styles["ad-prompt-actions"]}>
            <form action={setMode.bind(null, "prod")}>
              <button type="submit" className="sb-btn">
                Byt till riktiga stamboken
              </button>
            </form>
            <Link href="/stamboken" className="sb-btn sb-btn-secondary">
              Tillbaka
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // 2. Role gate: 404, not 403 (URL-enumeration hardening).
  const user = await getUser();
  if (!user) notFound();
  if (!hasAnyVisible(user)) notFound();

  // Manager-fliken och mastheadens rollrad behöver genbanksnamn
  // ("Besättningar i <gb-name>").
  let gbNames: string[] | undefined;
  if (!user.is_admin && user.is_manager?.length) {
    try {
      // GET /api/genebanks returns { genebanks: [...] } (herdbook.py), not a
      // bare array — same unwrap as anvandare/[userId]/page.tsx.
      const res = await fetchApi<{ genebanks: GenebankShort[] }>("/genebanks", {
        forceProd: true,
      });
      const gbs = res.genebanks ?? [];
      gbNames = gbs
        .filter((g) => user.is_manager!.includes(g.id))
        .map((g) => g.name);
    } catch {
      gbNames = undefined; // label falls back to "din genbank"
    }
  }

  const roleLine = adminRoleLine(user, gbNames);

  return (
    <>
      <header className={styles["ad-masthead"]}>
        <div className={styles["ad-container"]}>
          <div className={`sb-eyebrow ${styles["ad-masthead-eyebrow"]}`}>
            Stamboken · Administration
          </div>
          <h1 className={`sb-h4 ${styles["ad-masthead-title"]}`}>Adminpanel</h1>
          <div className={styles["ad-masthead-meta"]}>{roleLine}</div>
        </div>
      </header>
      <AdminTabs user={user} gbNames={gbNames} />
      {/* DashboardShell renderar redan <main> (dashboard-shell.tsx:16) —
          detta är en <div>, aldrig en nästlad main. */}
      <div className={`${styles["ad-container"]} ${styles["ad-main"]}`}>
        {children}
      </div>
    </>
  );
}
