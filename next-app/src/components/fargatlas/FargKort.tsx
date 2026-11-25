import { fotoUrl, type AtlasFarg } from "@/lib/fargatlas/atlas";
import styles from "./fargatlas.module.css";

/** One colour of the atlas: photo, number, name, comment, the atlas's description and what sets it apart. */
export function FargKort({
  farg,
  fotoBas,
}: {
  farg: AtlasFarg;
  fotoBas: string;
}) {
  return (
    <article className={`sb-card ${styles.kort}`} id={`farg-${farg.id}`}>
      {farg.foton.length === 0 ? (
        <div className={styles.utanFoto}>Foto saknas</div>
      ) : (
        farg.foton.map((foto) => (
          <figure key={foto.id} className={styles.foto}>
            <a
              href={fotoUrl(fotoBas, foto.id, 1600)}
              target="_blank"
              rel="noopener"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- next/image would fetch the photo without the visitor's session */}
              <img
                src={fotoUrl(fotoBas, foto.id, 480)}
                alt={`${farg.id} ${farg.name}, större bild`}
                loading="lazy"
              />
            </a>
            {(foto.bildtext || foto.fotograf) && (
              <figcaption>
                {foto.bildtext}
                {foto.bildtext && foto.fotograf && " · "}
                {foto.fotograf && `Foto: ${foto.fotograf}`}
              </figcaption>
            )}
          </figure>
        ))
      )}
      <div className={styles.text}>
        <h3 className={styles.namn}>
          <span className={styles.nummer}>{farg.id}</span> {farg.name}
        </h3>
        {farg.comment && <p className={styles.kommentar}>{farg.comment}</p>}
        {farg.beskrivning && <p>{farg.beskrivning}</p>}
        {farg.skiljs_fran && (
          <p>
            <strong>Skiljs från:</strong> {farg.skiljs_fran}
          </p>
        )}
      </div>
    </article>
  );
}
