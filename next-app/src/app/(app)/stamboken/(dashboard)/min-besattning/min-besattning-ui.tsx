"use client";

import React from "react";
import type { Individual } from "@/redux/api/apiSlice";
import type { SbIconName } from "@/components/shell/SbIcon";
import styles from "./min-besattning.module.css";

export type TabValue = "overview" | "individuals" | "breeding" | "pedigree";

export const MB_TABS: { key: TabValue; label: string; icon: SbIconName }[] = [
  { key: "overview", label: "Översikt", icon: "grid" },
  { key: "individuals", label: "Kaniner", icon: "rabbit" },
  { key: "breeding", label: "Kullar och parningar", icon: "heart" },
  { key: "pedigree", label: "Släktträd", icon: "pedigree" },
];

export interface BreedingRecord {
  id: number;
  mother: string;
  mother_name?: string | null;
  father: string;
  father_name?: string | null;
  breed_date: string | null;
  birth_date: string | null;
  litter_number?: number | null;
  litter_size?: number | null;
  litter_size6w?: number | null;
  breed_notes?: string | null;
  birth_notes?: string | null;
  breeding_herd?: string | null;
  individuals?: { number: string; name?: string | null; sex?: string | null }[];
}

/* Unchanged semantics from the pre-split component (TabPanel in
   min-besattning-content.tsx) */
export function TabPanel(props: {
  children?: React.ReactNode;
  index: string;
  value: string;
}) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`herd-tabpanel-${index}`}
      aria-labelledby={`herd-tab-${index}`}
      {...other}
    >
      {value === index && <div style={{ paddingTop: 0 }}>{children}</div>}
    </div>
  );
}

/* sv-SE helpers, ported from surfaces/min-besattning-data.jsx lines 88-108.
   All callers render strictly post-hydration (content keeps the isHydrated
   gate), so Date.now() here cannot cause SSR/client markup mismatches. */
export function mbDate(d: string): string {
  return new Date(d).toLocaleDateString("sv-SE", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function mbAge(birth: string | null | undefined): string {
  if (!birth) return "—";
  const days = Math.floor((Date.now() - new Date(birth).getTime()) / 86400000);
  if (days < 0) return "—";
  if (days < 30) return `${days} dagar`;
  if (days < 365) return `${Math.floor(days / 30)} mån`;
  const y = Math.floor(days / 365);
  const m = Math.floor((days % 365) / 30);
  return m > 0 ? `${y} år ${m} mån` : `${y} år`;
}

export function mbGestation(mateDate: string): {
  day: number;
  due: string;
  pct: number;
} {
  const day = Math.floor(
    (Date.now() - new Date(mateDate).getTime()) / 86400000,
  );
  const due = new Date(new Date(mateDate).getTime() + 31 * 86400000);
  return {
    day,
    due: due.toISOString().slice(0, 10),
    pct: Math.min(100, Math.round((day / 31) * 100)),
  };
}

export type RabbitStatus = "Aktiv" | "Död" | "Inaktiv";

/* Mirrors the status semantics of the pre-split calculateStats/recentRabbits */
export function rabbitStatus(ind: Individual): RabbitStatus {
  if (ind.death_date || ind.alive === false) return "Död";
  if (ind.is_active) return "Aktiv";
  return "Inaktiv";
}

/* Status badge tones per handoff README: Aktiv=mossa, Död/Inaktiv=neutral */
export function MbStatus({ status }: { status: RabbitStatus }) {
  const tone = status === "Aktiv" ? " sb-badge-mossa" : "";
  return <span className={`sb-badge${tone}`}>{status}</span>;
}

export function MbSex({ sex }: { sex?: string | null }) {
  if (sex !== "female" && sex !== "male") return null;
  return (
    <span className={styles["mb-sex"]} data-sex={sex}>
      {sex === "female" ? "♀ Hona" : "♂ Hane"}
    </span>
  );
}

/* Section card with serif-adjacent title row (prototype MbCard,
   surfaces/min-besattning-ui.jsx lines 109-121) */
export function MbCard({
  title,
  action,
  children,
  pad = true,
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  pad?: boolean;
}) {
  return (
    <section className={`sb-card ${styles["mb-section-card"]}`}>
      {(title || action) && (
        <header className={styles["mb-card-head"]}>
          <h2 className="sb-h6" style={{ margin: 0 }}>
            {title}
          </h2>
          {action}
        </header>
      )}
      <div style={pad ? { padding: "0 20px 20px" } : undefined}>{children}</div>
    </section>
  );
}

export function MbStat({
  num,
  label,
  hint,
}: {
  num: number | string;
  label: string;
  hint?: string;
}) {
  return (
    <div className={styles["mb-stat"]} title={hint || ""}>
      <div className="sb-stat-num">{num}</div>
      <div className="sb-stat-label">{label}</div>
    </div>
  );
}

/* role="button" contract: activate on BOTH Enter and Space (Space must not
   scroll the page). Shared by MbRabbitRow and KaninerTab's cards. */
export function mbPressable(onClick: () => void) {
  return {
    role: "button" as const,
    tabIndex: 0,
    onClick,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onClick();
      }
    },
  };
}

export function MbRabbitRow({
  ind,
  onClick,
}: {
  ind: Individual;
  onClick: () => void;
}) {
  const status = rabbitStatus(ind);
  const cert = ind.digital_certificate ?? ind.certificate;
  return (
    <div className={styles["mb-rabbit-row"]} {...mbPressable(onClick)}>
      <div className={styles["mb-row-id"]}>
        <span className="sb-meta">{ind.number}</span>
        <span className={styles["mb-row-name"]}>
          {ind.name || `Kanin ${ind.number}`}
        </span>
      </div>
      <div className={styles["mb-row-meta"]}>
        <MbSex sex={ind.sex} />
        <span className={styles["mb-age"]}>{mbAge(ind.birth_date)}</span>
      </div>
      <div className={styles["mb-row-badges"]}>
        <MbStatus status={status} />
        {cert != null && (
          <span className={`sb-badge ${styles["mb-hide-sm"]}`}>
            Intyg {cert}
          </span>
        )}
      </div>
      <span className={styles["mb-chevron"]} aria-hidden="true">
        ›
      </span>
    </div>
  );
}

export function MbGestationBar({ breeding }: { breeding: BreedingRecord }) {
  const g = mbGestation(breeding.breed_date!);
  return (
    <div className={styles["mb-gestation"]}>
      <div className={styles["mb-gestation-head"]}>
        <span>
          <strong>{breeding.mother_name || breeding.mother}</strong> ×{" "}
          {breeding.father_name || breeding.father}
        </span>
        <span className="sb-meta">dag {g.day} av 31</span>
      </div>
      <div className={styles["mb-progress"]}>
        <div
          className={styles["mb-progress-fill"]}
          style={{ width: `${g.pct}%` }}
        />
      </div>
      <div className="sb-meta" style={{ marginTop: 6 }}>
        Beräknad kull {mbDate(g.due)}
        {breeding.breed_notes ? ` · ${breeding.breed_notes}` : ""}
      </div>
    </div>
  );
}

/* Per-field privacy badge, handoff README:
   authenticated = mossa "◉ Inloggade besättningar",
   private = neutral "🔒 Endast genbanksansvarig" */
export const MB_PRIVACY_LABEL: Record<string, string> = {
  authenticated: "Inloggade besättningar",
  private: "Endast genbanksansvarig",
};

export function MbPrivacy({ level }: { level: string }) {
  const authed = level === "authenticated";
  return (
    <span
      className={`sb-badge${authed ? " sb-badge-mossa" : ""}`}
      title="Vem ser uppgiften"
    >
      {authed ? "◉" : "🔒"}{" "}
      {MB_PRIVACY_LABEL[authed ? "authenticated" : "private"]}
    </span>
  );
}
