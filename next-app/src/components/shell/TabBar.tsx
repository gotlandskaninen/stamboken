import Link from "next/link";
import { SbIcon, type SbIconName } from "./SbIcon";
import styles from "./shell.module.css";

export function TabBar({
  tabs,
  active,
  makeHref,
  idBase,
}: {
  tabs: { key: string; label: string; icon: SbIconName }[];
  active: string;
  makeHref: (key: string) => string;
  /** When set, each tab gets id `${idBase}-tab-${key}` and
      aria-controls `${idBase}-tabpanel-${key}` so external tabpanels'
      aria-labelledby can resolve. */
  idBase?: string;
}) {
  return (
    <div className={styles.tabsWrap}>
      <div className={styles.tabs} role="tablist" aria-label="Vyer">
        {tabs.map((tab) => {
          const selected = tab.key === active;
          return (
            <Link
              key={tab.key}
              href={makeHref(tab.key)}
              role="tab"
              aria-selected={selected}
              id={idBase ? `${idBase}-tab-${tab.key}` : undefined}
              aria-controls={
                idBase ? `${idBase}-tabpanel-${tab.key}` : undefined
              }
              className={`${styles.tab} ${selected ? styles.tabActive : ""}`}
            >
              <SbIcon name={tab.icon} size={16} />
              {tab.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
