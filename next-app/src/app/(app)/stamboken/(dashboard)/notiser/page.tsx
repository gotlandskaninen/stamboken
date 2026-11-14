import { fetchApi } from "@/lib/api";
import { Masthead } from "@/components/shell/Masthead";
import type { Notice } from "@/lib/inkorg";
import { NoticeList } from "./NoticeList";
import styles from "../inskick/inskick.module.css";

export const dynamic = "force-dynamic";

export const metadata = { title: "Notiser" };

export default async function NotiserPage() {
  const { notices, unread } = await fetchApi<{
    notices: Notice[];
    unread: number;
  }>("/v2/inkorg/notiser");

  return (
    <>
      <Masthead eyebrow="Inläsning" title="Notiser" />
      <div className={styles.container}>
        {notices.length === 0 ? (
          <section className="sb-card">
            <div className={styles.cardBody}>
              <p className={styles.note} style={{ margin: 0 }}>
                Inga notiser. Här dyker det upp när något händer med ett av dina
                inskick.
              </p>
            </div>
          </section>
        ) : (
          <NoticeList notices={notices} unread={unread} />
        )}
      </div>
    </>
  );
}
