import { EUFundingBadge } from "@/components/public/EUFundingBadge";
import styles from "./shell.module.css";

export function ShellFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.footerInner}>
        <div className={styles.footerFunding}>
          <EUFundingBadge orientation="horizontal" height={44} />
          <span>
            Verksamheten medfinansieras av{" "}
            <strong>Europeiska jordbruksfonden för landsbygdsutveckling</strong>{" "}
            — Europa investerar i landsbygdsområden.
          </span>
        </div>
        <span>
          © 2026 Föreningen Gotlandskaninen ·{" "}
          <a href="https://github.com/gotlandskaninen/stamboken">Källkod</a>
        </span>
      </div>
    </footer>
  );
}
