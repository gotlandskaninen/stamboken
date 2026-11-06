"use client";

import React from "react";
import { useRouter } from "next/navigation";
import type { Individual } from "@/redux/api/apiSlice";
import {
  MbCard,
  MbStat,
  MbRabbitRow,
  MbGestationBar,
  rabbitStatus,
  type BreedingRecord,
  type TabValue,
} from "./min-besattning-ui";
import BesattningsuppgifterCard from "./BesattningsuppgifterCard";
import styles from "./min-besattning.module.css";

interface OversiktTabProps {
  herd: any;
  breedings: BreedingRecord[] | null;
  herdNumber: string;
  onGoTab: (tab: TabValue) => void;
  onNewLitter: () => void;
  onNewMating: () => void;
}

interface Todo {
  badge: string;
  badgeCls: string;
  text: string;
}

export default function OversiktTab({
  herd,
  breedings,
  herdNumber,
  onGoTab,
  onNewLitter,
  onNewMating,
}: OversiktTabProps) {
  const router = useRouter();
  const individuals: Individual[] = herd?.individuals || [];

  const active = individuals.filter((i) => rabbitStatus(i) === "Aktiv");
  const stats = {
    active: active.length,
    breeding: active.filter(
      (i) => !i.castration_date && (i.sex === "female" || i.sex === "male"),
    ).length,
    certs: individuals.filter((i) => i.certificate || i.digital_certificate)
      .length,
    litters: (breedings ?? []).filter((b) =>
      b.birth_date?.startsWith(String(new Date().getFullYear())),
    ).length,
  };

  const matings = (breedings ?? [])
    .filter((b) => !b.birth_date && b.breed_date)
    .sort((a, b) => (a.breed_date || "").localeCompare(b.breed_date || ""));

  // Same "last five active" selection as the old recentRabbits,
  // newest first for display
  const recent = active.slice(-5).reverse();

  // Single clock read for the derived "days since" values below. The tab only
  // renders behind the isHydrated gate in min-besattning-content.tsx, so a
  // time-dependent render cannot cause an SSR/client markup mismatch (same
  // rationale as the mb* date helpers in min-besattning-ui.tsx).
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const todos: Todo[] = [];
  for (const b of breedings ?? []) {
    if (!b.birth_date) continue;
    const ageDays = Math.floor(
      (now - new Date(b.birth_date).getTime()) / 86400000,
    );
    const expected = b.litter_size6w ?? b.litter_size ?? 0;
    const registered = b.individuals?.length ?? 0;
    if (ageDays >= 42 && registered < expected) {
      todos.push({
        badge: "Kullista",
        badgeCls: "sb-badge-lera",
        text: `${b.mother_name || b.mother}s kull${
          b.litter_number != null ? ` (Kull ${b.litter_number})` : ""
        } har passerat 6 veckor — registrera eller markera ungarnas öde.`,
      });
    }
  }
  for (const b of matings) {
    const day = Math.floor(
      (now - new Date(b.breed_date as string).getTime()) / 86400000,
    );
    if (day > 35) {
      todos.push({
        badge: "Parning",
        badgeCls: "sb-badge-himmel",
        text: `${b.mother_name || b.mother} × ${
          b.father_name || b.father
        } — dag ${day} utan registrerad födsel. Registrera födsel eller ta bort parningen.`,
      });
    }
  }

  return (
    <div>
      <div className={`sb-card ${styles["mb-stats"]}`}>
        <MbStat
          num={stats.active}
          label="Aktiva kaniner"
          hint="Registrerade och årsrapporterade inom 13 månader"
        />
        <MbStat num={stats.breeding} label="Avelsdjur" />
        <MbStat num={stats.certs} label="Utfärdade intyg" />
        <MbStat num={stats.litters} label="Kullar i år" />
      </div>

      <div className={styles["mb-two-col"]}>
        <div className={styles["mb-col-main"]}>
          <MbCard
            title="Pågående dräktigheter"
            action={
              <button
                type="button"
                className="sb-btn sb-btn-ghost sb-btn-sm"
                onClick={() => onGoTab("breeding")}
              >
                Alla parningar →
              </button>
            }
          >
            {matings.length === 0 ? (
              <p className="sb-meta" style={{ margin: 0 }}>
                Inga pågående parningar.
              </p>
            ) : (
              <div className={styles["mb-stack"]}>
                {matings.map((b) => (
                  <MbGestationBar key={b.id} breeding={b} />
                ))}
              </div>
            )}
          </MbCard>

          <MbCard
            title="Senaste kaninerna"
            pad={false}
            action={
              <button
                type="button"
                className="sb-btn sb-btn-ghost sb-btn-sm"
                onClick={() => onGoTab("individuals")}
              >
                Alla kaniner →
              </button>
            }
          >
            <div className={styles["mb-list"]}>
              {recent.map((ind) => (
                <MbRabbitRow
                  key={ind.number}
                  ind={ind}
                  onClick={() =>
                    router.push(
                      `/stamboken/individ/${encodeURIComponent(
                        ind.number || "",
                      )}`,
                    )
                  }
                />
              ))}
            </div>
          </MbCard>
        </div>

        <div className={styles["mb-col-side"]}>
          <MbCard title="Att göra">
            {todos.length === 0 ? (
              <p className="sb-meta" style={{ margin: 0 }}>
                Inget att göra just nu.
              </p>
            ) : (
              <div className={styles["mb-stack"]}>
                {todos.map((todo, i) => (
                  <div key={i} className={styles["mb-todo"]}>
                    <span className={`sb-badge ${todo.badgeCls}`}>
                      {todo.badge}
                    </span>
                    <p>{todo.text}</p>
                  </div>
                ))}
              </div>
            )}
          </MbCard>

          <MbCard title="Snabbåtgärder">
            <div className={styles["mb-actions"]}>
              <button
                type="button"
                className="sb-btn"
                style={{ width: "100%" }}
                onClick={onNewLitter}
              >
                + Registrera kull
              </button>
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                style={{ width: "100%" }}
                onClick={onNewMating}
              >
                Ny parning
              </button>
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                style={{ width: "100%" }}
                disabled
                title="Kommer snart"
              >
                Skapa genbanksintyg
              </button>
              <button
                type="button"
                className="sb-btn sb-btn-secondary"
                style={{ width: "100%" }}
                title="Kaniner registreras via kullistan under Kullar och parningar"
                onClick={() => onGoTab("breeding")}
              >
                Registrera ny kanin
              </button>
            </div>
          </MbCard>

          <BesattningsuppgifterCard herd={herd} herdNumber={herdNumber} />
        </div>
      </div>
    </div>
  );
}
