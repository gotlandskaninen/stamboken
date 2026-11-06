import styles from "./shell.module.css";

export function Masthead({
  eyebrow,
  title,
  meta,
  actions,
}: {
  eyebrow: string;
  title: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className={styles.masthead}>
      <div className={styles.mastheadInner}>
        <div className={styles.mastheadRow}>
          <div>
            <div className="sb-eyebrow">{eyebrow}</div>
            <h1 className={styles.title}>{title}</h1>
            {meta && <div className={styles.meta}>{meta}</div>}
          </div>
          {actions && <div className={styles.herdSwitch}>{actions}</div>}
        </div>
      </div>
    </div>
  );
}
