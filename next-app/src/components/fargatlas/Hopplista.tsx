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
      <form
        className={styles.nummerVal}
        onSubmit={(e) => {
          e.preventDefault();
          const nummer = new FormData(e.currentTarget).get("nummer");
          if (nummer) location.hash = `farg-${nummer}`;
        }}
      >
        <label htmlFor="ga-till-nummer">Gå till nummer</label>
        <select id="ga-till-nummer" name="nummer" defaultValue="">
          <option value="" disabled>
            Välj färg
          </option>
          {farger.map((f) => (
            <option key={f.id} value={f.id}>
              {f.id} {f.name}
            </option>
          ))}
        </select>
        <button type="submit" className="sb-btn sb-btn-secondary">
          Visa
        </button>
      </form>
    </nav>
  );
}
