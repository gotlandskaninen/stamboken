import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { Masthead } from "@/components/shell/Masthead";
import { KontoCard } from "./KontoCard";
import { MedlemskapCard } from "./MedlemskapCard";
import { KontaktClient } from "./KontaktClient";
import { PubliceringClient } from "./PubliceringClient";
import { PersonerClient } from "./PersonerClient";
import { NotisClient } from "./NotisClient";
import type { Me, MyMembership } from "./types";
import styles from "./profil.module.css";

export const dynamic = "force-dynamic";

// 404 = no member record / no active person row — the graceful states.
// Everything else bubbles to the route's error boundary (ADR-0008).
async function fetchOr404Null<T>(path: string): Promise<T | null> {
  try {
    return await fetchApi<T>(path);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

function InfoCard({ children }: { children: React.ReactNode }) {
  return (
    <section className="sb-card">
      <div className={styles.cardBody} style={{ paddingTop: 20 }}>
        <p className={styles.note} style={{ margin: 0 }}>
          {children}
        </p>
      </div>
    </section>
  );
}

export default async function ProfilPage() {
  const user = await requireUser();
  const [me, myMembership, notice] = await Promise.all([
    fetchOr404Null<Me>("/v2/members/me"),
    fetchOr404Null<MyMembership>("/v2/my-membership"),
    // Everyone has notices, member record or not; a failure just hides the card.
    fetchApi<{ mail_enabled: boolean }>("/v2/inkorg/notiser/installning").catch(
      () => null,
    ),
  ]);
  // After migrate_28_to_29 both endpoints resolve the same row; a mismatch
  // is an integrity state, never a normal UI state.
  const conflict =
    me !== null &&
    (myMembership === null || me.membership.id !== myMembership.membership.id);
  const readOnly = me?.role !== "huvudmedlem";

  return (
    <>
      <Masthead eyebrow="Konto" title="Min profil" meta={user.email} />
      <div className={styles.container}>
        <div className={styles.grid}>
          <aside className={styles.side}>
            <KontoCard user={user} />
          </aside>
          <div className={styles.main}>
            {me === null ? (
              <InfoCard>
                Du har ingen medlemspost kopplad till ditt konto.
              </InfoCard>
            ) : conflict || myMembership === null ? (
              <InfoCard>
                Ditt konto är kopplat till flera medlemsposter — kontakta
                matrikelansvarig.
              </InfoCard>
            ) : (
              <>
                <MedlemskapCard me={me} herds={myMembership.membership.herds} />
                <KontaktClient
                  readOnly={readOnly}
                  initial={{
                    phone: me.phone ?? "",
                    email: me.email ?? "",
                    address: me.membership.address ?? "",
                    postal_code: me.membership.postal_code ?? "",
                    city: me.membership.city ?? "",
                  }}
                />
                <PubliceringClient
                  readOnly={readOnly}
                  initial={me.publication_consent}
                  answered={me.consent_answered}
                />
                <PersonerClient
                  isMainMember={myMembership.is_main_member}
                  persons={myMembership.membership.persons}
                  herds={myMembership.membership.herds}
                />
              </>
            )}
            {notice && <NotisClient initial={notice.mail_enabled} />}
          </div>
        </div>
      </div>
    </>
  );
}
