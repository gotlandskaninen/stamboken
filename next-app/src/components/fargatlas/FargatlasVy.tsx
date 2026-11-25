import { grupperFor, type Fargatlas } from "@/lib/fargatlas/atlas";
import { FargKort } from "./FargKort";
import styles from "./fargatlas.module.css";

/** Every colour, grouped as the key groups them (by genebank without a key), with the atlas's text about each group. */
export function FargatlasVy({
  atlas,
  fotoBas,
}: {
  atlas: Fargatlas;
  fotoBas: string;
}) {
  const farger = new Map(atlas.farger.map((f) => [f.id, f]));
  const nyckelgrupper = grupperFor(atlas);
  const grupperade = new Set(nyckelgrupper.flatMap((g) => g.nummer));
  // A colour added after the key was written is still shown, last.
  const ovriga = atlas.farger.filter((f) => !grupperade.has(f.id));
  const grupper = [
    ...nyckelgrupper.map((g) => ({
      ...g,
      farger: g.nummer.flatMap((n) => farger.get(n) ?? []),
    })),
    ...(ovriga.length
      ? [{ id: "ovriga", namn: "Övriga färger", farger: ovriga }]
      : []),
  ];
  return (
    <>
      {grupper.map((grupp) => (
        <section
          key={grupp.id}
          aria-labelledby={`grupp-${grupp.id}`}
          className={styles.grupp}
        >
          <h2 id={`grupp-${grupp.id}`} className={styles.gruppNamn}>
            {grupp.namn}
          </h2>
          {atlas.grupper[grupp.id]?.beskrivning && (
            <p className={styles.gruppText}>
              {atlas.grupper[grupp.id]?.beskrivning}
            </p>
          )}
          <div className={styles.lista}>
            {grupp.farger.map((farg) => (
              <FargKort key={farg.id} farg={farg} fotoBas={fotoBas} />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
