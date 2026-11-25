import { Masthead } from "@/components/shell/Masthead";
import { FargatlasVy } from "@/components/fargatlas/FargatlasVy";
import styles from "@/components/fargatlas/fargatlas.module.css";
import { getFargatlas } from "./actions";
import { SkrivUt } from "./SkrivUt";

export const dynamic = "force-dynamic";

export const metadata = { title: "Färgatlas" };

export default async function FargatlasPage() {
  const data = await getFargatlas();
  return (
    <>
      <Masthead eyebrow="Färger" title="Färgatlas" actions={<SkrivUt />} />
      <div className={styles.container}>
        <p className={styles.intro}>
          Föreningens färgnummer med foto och beskrivning, ordnade i grupper.
          Färgnumret anger grundfärgen, också när pälsen är rex: välj då Rex vid
          Päls.
        </p>
        {data ? (
          <FargatlasVy atlas={data.atlas} fotoBas={data.fotoBas} />
        ) : (
          <p role="alert">
            Färgatlasen gick inte att hämta. Försök igen senare.
          </p>
        )}
      </div>
    </>
  );
}
