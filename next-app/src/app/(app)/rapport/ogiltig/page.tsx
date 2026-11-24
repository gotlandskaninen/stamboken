import { fetchApi } from "@/lib/api";
import styles from "../../stamboken/(dashboard)/arsrapport/arsrapport.module.css";

export const dynamic = "force-dynamic";

type Contact = { ras: string; namn: string; telefon: string };

// Who to call. Without the list (none set, or the API is down) the text alone stands.
async function contacts(): Promise<Contact[]> {
  try {
    return await fetchApi<Contact[]>("/v2/rapport/kontakt", {
      forceProd: true,
    });
  } catch {
    return [];
  }
}

export default async function InvalidLinkPage() {
  const list = await contacts();
  return (
    <div className={styles.root}>
      <h1 className={styles.title}>Årsrapport</h1>
      <p className={styles.lead}>
        Länken gäller inte längre. Har du fått ett nyare mejl från Stamboken?
        Använd länken i det.
      </p>
      {list.length > 0 && (
        <ul>
          {list.map((c) => (
            <li key={`${c.ras}-${c.telefon}`}>
              {c.ras}: {c.namn},{" "}
              <a href={`tel:${c.telefon.replace(/[^\d+]/g, "")}`}>
                {c.telefon}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
