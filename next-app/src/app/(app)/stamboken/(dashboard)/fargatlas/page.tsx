import Link from "next/link";
import { Masthead } from "@/components/shell/Masthead";
import { FargatlasVy } from "@/components/fargatlas/FargatlasVy";
import { FargNyckel } from "@/components/fargatlas/FargNyckel";
import { Hopplista } from "@/components/fargatlas/Hopplista";
import { NyckelLista } from "@/components/fargatlas/NyckelLista";
import styles from "@/components/fargatlas/fargatlas.module.css";
import { grupperFor } from "@/lib/fargatlas/atlas";
import { kontrollera } from "@/lib/fargatlas/nyckel";
import { getFargatlas } from "./actions";
import { SkrivUt } from "./SkrivUt";

export const dynamic = "force-dynamic";

export const metadata = { title: "Färgatlas" };

export default async function FargatlasPage() {
  const data = await getFargatlas();
  // The guide and the printed key need a whole key from the atlas package; without one the colours still show.
  const nyckel =
    data?.atlas.nyckel && !kontrollera(data.atlas.nyckel)
      ? data.atlas.nyckel
      : null;
  return (
    <>
      <Masthead eyebrow="Färger" title="Färgatlas" actions={<SkrivUt />} />
      <div className={styles.container}>
        <p className={styles.intro}>
          Föreningens färgnummer med foto och beskrivning, ordnade i grupper.
          Färgnumret anger grundfärgen, också när pälsen är rex: välj då Rex vid
          Päls.
        </p>
        {!data ? (
          <p role="alert">
            Färgatlasen gick inte att hämta.{" "}
            <Link href="/stamboken/fargatlas">Försök igen</Link>
          </p>
        ) : (
          <>
            {nyckel && (
              <section
                className={`sb-card ${styles.nyckelSektion}`}
                aria-labelledby="hjalp-mig-valja"
              >
                <div className={styles.nyckelHuvud}>
                  <h2 id="hjalp-mig-valja" className={styles.gruppNamn}>
                    Hjälp mig välja
                  </h2>
                  <p className={styles.hjalp}>
                    Svara på frågorna om din kanin, så kommer du fram till ett
                    färgnummer. Nyckeln gäller gotlandskanin.
                  </p>
                </div>
                <div className={styles.nyckelKropp}>
                  <FargNyckel data={data} />
                </div>
              </section>
            )}
            {nyckel && (
              <NyckelLista nyckel={nyckel} farger={data.atlas.farger} />
            )}
            <Hopplista
              grupper={grupperFor(data.atlas)}
              farger={data.atlas.farger}
            />
            <FargatlasVy atlas={data.atlas} fotoBas={data.fotoBas} />
          </>
        )}
      </div>
    </>
  );
}
