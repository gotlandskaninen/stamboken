"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { fotoUrl } from "@/lib/fargatlas/atlas";
import { kontrollera, vandra, type Nyckel } from "@/lib/fargatlas/nyckel";
import type { AtlasData } from "./useFargatlas";
import styles from "./fargatlas.module.css";

/**
 * "Hjälp mig välja": the key's questions one at a time, with the answers so far as a trail, ending in the colour
 * number. With `onValj`, "Välj" hands the number back with the reminders the user said yes to (Rex, blue eyes);
 * the guide never sets the coat itself.
 */
export function FargNyckel({
  data,
  onValj,
  saknas,
}: {
  data: AtlasData | undefined;
  onValj?: (nummer: number, paminnelser: string[]) => void;
  /** A number "Välj" could not set because the colour list lacks it; said at that number only. */
  saknas?: number | null;
}) {
  const [svar, setSvar] = useState<string[]>([]);
  const [efter, setEfter] = useState<Record<string, boolean>>({});
  const rubrik = useRef<HTMLHeadingElement>(null);
  // In a dialog the first question takes the focus at once; on the page only after the user's first step.
  const flyttat = useRef(!!onValj);
  useEffect(() => {
    if (flyttat.current) rubrik.current?.focus();
  }, [svar, data]);
  const ga = (nya: string[]) => {
    flyttat.current = true;
    setEfter({});
    setSvar(nya);
  };

  if (data === undefined) return <p>Hämtar nyckeln …</p>;
  const nyckel = data?.atlas.nyckel;
  if (!nyckel || kontrollera(nyckel)) {
    return (
      <p role="alert">
        Hjälp mig välja går inte att använda just nu. Välj färgen i listan i
        stället.
      </p>
    );
  }

  const steg = vandra(svar, nyckel);
  const navigering = svar.length > 0 && (
    <div className={styles.knappar}>
      <button
        type="button"
        className="sb-btn sb-btn-ghost"
        onClick={() => ga(svar.slice(0, -1))}
      >
        Tillbaka
      </button>
      <button
        type="button"
        className="sb-btn sb-btn-ghost"
        onClick={() => ga([])}
      >
        Börja om
      </button>
    </div>
  );

  return (
    <div className={styles.nyckel}>
      {svar.length > 0 && <Spar nyckel={nyckel} svar={svar} ga={ga} />}
      {"fraga" in steg ? (
        <>
          <p className={styles.steg}>Fråga {svar.length + 1}</p>
          <h3 ref={rubrik} tabIndex={-1} className={styles.fraga}>
            {nyckel.fragor[steg.fraga].text}
          </h3>
          {nyckel.fragor[steg.fraga].hjalp && (
            <p className={styles.hjalp}>{nyckel.fragor[steg.fraga].hjalp}</p>
          )}
          <div className={styles.svar}>
            {nyckel.fragor[steg.fraga].svar.map((s) => (
              <button
                key={s.id}
                type="button"
                className={styles.svarKnapp}
                onClick={() => ga([...svar, s.id])}
              >
                <span>
                  {s.text}
                  {s.hjalp && (
                    <>
                      {" "}
                      <span className={styles.hjalp}>{s.hjalp}</span>
                    </>
                  )}
                </span>
                <span aria-hidden="true" className={styles.pil}>
                  ›
                </span>
              </button>
            ))}
          </div>
          {navigering}
        </>
      ) : (
        <Resultat
          nyckel={nyckel}
          data={data}
          nummer={steg.nummer}
          anteckning={steg.anteckning}
          efter={efter}
          setEfter={setEfter}
          rubrik={rubrik}
          onValj={onValj}
          saknas={saknas}
          navigering={navigering}
        />
      )}
    </div>
  );
}

/** The answers so far; each one goes back to its question. */
function Spar({
  nyckel,
  svar,
  ga,
}: {
  nyckel: Nyckel;
  svar: string[];
  ga: (nya: string[]) => void;
}) {
  // Each answer with the question it answered, following the path from the start.
  const steg = svar.reduce<
    { i: number; fraga: string; text: string; till: string }[]
  >((rader, id, i) => {
    const q = i === 0 ? nyckel.start : rader[i - 1].till;
    const s = nyckel.fragor[q].svar.find((x) => x.id === id)!;
    return [
      ...rader,
      { i, fraga: nyckel.fragor[q].text, text: s.text, till: String(s.till) },
    ];
  }, []);
  return (
    <ol className={styles.spar} aria-label="Dina svar">
      {steg.map(({ i, fraga, text }) => (
        <li key={i}>
          <button
            type="button"
            className={styles.sparSteg}
            onClick={() => ga(svar.slice(0, i))}
            aria-label={`Ändra fråga ${i + 1}, ${fraga} Du svarade ${text}.`}
          >
            {text}
          </button>
        </li>
      ))}
    </ol>
  );
}

function Resultat({
  nyckel,
  data,
  nummer,
  anteckning,
  efter,
  setEfter,
  rubrik,
  onValj,
  saknas,
  navigering,
}: {
  nyckel: Nyckel;
  data: NonNullable<AtlasData>;
  nummer: number;
  anteckning?: string;
  efter: Record<string, boolean>;
  setEfter: (e: Record<string, boolean>) => void;
  rubrik: React.RefObject<HTMLHeadingElement | null>;
  onValj?: (nummer: number, paminnelser: string[]) => void;
  saknas?: number | null;
  navigering: React.ReactNode;
}) {
  const farg = data.atlas.farger.find((f) => f.id === nummer);
  const fragor = nyckel.efter_numret ?? [];
  const paminnelser = fragor.filter((q) => efter[q.id]).map((q) => q.ja);
  const foto = farg?.foton[0];
  return (
    <div className={styles.resultat}>
      <p className={styles.steg}>Resultat</p>
      <h3 ref={rubrik} tabIndex={-1} className={styles.resultatRubrik}>
        <span className={styles.resultatNummer}>{nummer}</span>
        {farg && ` ${farg.name}`}
      </h3>
      {farg?.comment && <p className={styles.hjalp}>{farg.comment}</p>}
      {foto && (
        // eslint-disable-next-line @next/next/no-img-element -- next/image would fetch the photo without the visitor's session
        <img
          className={styles.resultatFoto}
          src={fotoUrl(data.fotoBas, foto.id, 480)}
          alt={`Foto: ${nummer} ${farg?.name ?? ""}`}
        />
      )}
      {farg?.beskrivning && <p>{farg.beskrivning}</p>}
      {anteckning && (
        <p className={styles.anteckning}>
          <strong>Färganteckning:</strong> {anteckning}
        </p>
      )}
      {fragor.map((q) => (
        <fieldset key={q.id} className={styles.efter}>
          <legend>{q.text}</legend>
          <div className={styles.knappar}>
            {[true, false].map((ja) => (
              <button
                key={String(ja)}
                type="button"
                className={styles.jaNej}
                aria-pressed={efter[q.id] === ja}
                onClick={() => setEfter({ ...efter, [q.id]: ja })}
              >
                {ja ? "Ja" : "Nej"}
              </button>
            ))}
          </div>
          {efter[q.id] && (
            <p className={styles.paminnelse} role="status">
              {q.ja}
            </p>
          )}
        </fieldset>
      ))}
      {saknas === nummer && (
        <p role="alert">
          Färg {nummer} finns inte i färglistan. Stäng och välj färgen i fältet.
        </p>
      )}
      {onValj ? (
        <div className={styles.knappar}>
          <button
            type="button"
            className="sb-btn"
            onClick={() => onValj(nummer, paminnelser)}
          >
            Välj {nummer}
            {farg && ` ${farg.name}`}
          </button>
        </div>
      ) : (
        <p>
          Ange {nummer} som färg när du registrerar eller ändrar kaninen, i{" "}
          <Link href="/stamboken/min-besattning">Min besättning</Link>.
        </p>
      )}
      {navigering}
    </div>
  );
}
