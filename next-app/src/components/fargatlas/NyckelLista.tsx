import type { Nyckel } from "@/lib/fargatlas/nyckel";
import type { AtlasFarg } from "@/lib/fargatlas/atlas";
import styles from "./fargatlas.module.css";

/** The key on paper (the print view): every question numbered, each answer with where it leads. */
export function NyckelLista({
  nyckel,
  farger,
}: {
  nyckel: Nyckel;
  farger: AtlasFarg[];
}) {
  const ids = Object.keys(nyckel.fragor);
  const namn = new Map(farger.map((f) => [f.id, f.name]));
  return (
    <section
      className={styles.baraUtskrift}
      aria-label="Bestämningsnyckeln för gotlandskanin"
    >
      <h2 className={styles.gruppNamn}>Bestämningsnyckeln för gotlandskanin</h2>
      <p>
        Börja vid fråga 1 och följ svaren tills du kommer till ett färgnummer.
        En mellerudskanin får 100 eller 101 och går inte genom nyckeln.
      </p>
      <ol>
        {ids.map((id) => {
          const fraga = nyckel.fragor[id];
          return (
            <li key={id}>
              {fraga.text}
              {fraga.hjalp && ` ${fraga.hjalp}`}
              <ul>
                {fraga.svar.map((s) => (
                  <li key={s.id}>
                    {s.text}
                    {s.hjalp && ` (${s.hjalp})`} →{" "}
                    {typeof s.till === "number"
                      ? `${s.till} ${namn.get(s.till) ?? ""}`.trim()
                      : `fråga ${ids.indexOf(s.till) + 1}`}
                    {s.anteckning && `. ${s.anteckning}`}
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ol>
      <p>När du har ett nummer:</p>
      <ul>
        {(nyckel.efter_numret ?? []).map((q) => (
          <li key={q.id}>
            {q.text} Om ja: {q.ja}
          </li>
        ))}
      </ul>
    </section>
  );
}
