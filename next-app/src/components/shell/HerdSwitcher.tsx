"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import styles from "./shell.module.css";

export function HerdSwitcher({
  herds,
  active,
}: {
  herds: { id: string; label: string }[];
  active: string;
}) {
  const searchParams = useSearchParams();
  if (herds.length < 2) return null;
  // Preserve the active tab when switching herds: the existing handler
  // keeps both ?herd and ?tab, so a literal ?herd=X href must not drop ?tab.
  const tab = searchParams.get("tab");
  const hrefFor = (id: string) => {
    const params = new URLSearchParams();
    params.set("herd", id);
    if (tab) params.set("tab", tab);
    return `/stamboken/min-besattning?${params.toString()}`;
  };
  return (
    <div className={styles.herdSwitch}>
      {herds.map((herd) => (
        <Link
          key={herd.id}
          href={hrefFor(herd.id)}
          className={`${styles.herdChip} ${herd.id === active ? styles.herdChipActive : ""}`}
          aria-current={herd.id === active ? "true" : undefined}
        >
          {herd.label}
        </Link>
      ))}
    </div>
  );
}
