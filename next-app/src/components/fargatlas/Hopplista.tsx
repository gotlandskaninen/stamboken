"use client";

import type { AtlasFarg, Grupp } from "@/lib/fargatlas/atlas";
import styles from "./fargatlas.module.css";

/** A way into a long page: the groups as links, and every number in a list that jumps to its card. */
export function Hopplista({
  grupper,
  farger,
}: {
  grupper: Grupp[];
  farger: AtlasFarg[];
}) {
  return (
    <nav className={styles.hopplista} aria-label="Hoppa till">
      <ul className={styles.gruppLankar}>
        {grupper.map((g) => (
          <li key={g.id}>
            <a href={`#grupp-${g.id}`} className={styles.gruppLank}>
              {g.namn}
            </a>
          </li>
        ))}
      </ul>
      <label className={styles.nummerVal}>
        <span>Gå till nummer</span>
        <select
          defaultValue=""
          onChange={(e) => {
            if (e.target.value) location.hash = `farg-${e.target.value}`;
          }}
        >
          <option value="" disabled>
            Välj färg
          </option>
          {farger.map((f) => (
            <option key={f.id} value={f.id}>
              {f.id} {f.name}
            </option>
          ))}
        </select>
      </label>
    </nav>
  );
}
