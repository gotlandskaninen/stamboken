"use client";

import React, { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import type { Individual } from "@/redux/api/apiSlice";
import {
  MbSex,
  MbStatus,
  MbRabbitRow,
  mbAge,
  mbPressable,
  rabbitStatus,
} from "./min-besattning-ui";
import styles from "./min-besattning.module.css";

const RegisterRabbitDialog = dynamic(
  () =>
    import("@/components/herd/RegisterRabbitDialog").then(
      (m) => m.RegisterRabbitDialog,
    ),
  { ssr: false },
);

const VIEW_STORAGE_KEY = "minBesattning.kaninerView";

type KaninView = "cards" | "list";
type KaninFilter = "active" | "all" | "cert";

interface KaninerTabProps {
  individuals: Individual[];
  herdNumber: string;
  genebankId: number | null;
}

function photoUrl(ind: Individual): string | null {
  if (!ind.has_photo || !ind.number) return null;
  const v = ind.updated_at ? `?v=${new Date(ind.updated_at).getTime()}` : "";
  return `/uppladdningar/kaniner/${ind.number}.jpg${v}`;
}

function hasCert(ind: Individual): boolean {
  return ind.certificate != null || ind.digital_certificate != null;
}

function MbPhoto({ ind }: { ind: Individual }) {
  const url = photoUrl(ind);
  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={ind.name || ind.number || ""}
        className={styles["mb-photo"]}
      />
    );
  }
  return (
    <div className={`sb-placeholder ${styles["mb-photo-placeholder"]}`}>
      Foto saknas
    </div>
  );
}

function MbRabbitCard({
  ind,
  herdNumber,
  onClick,
}: {
  ind: Individual;
  herdNumber: string;
  onClick: () => void;
}) {
  const status = rabbitStatus(ind);
  const digital = ind.digital_certificate != null;
  const cert = ind.digital_certificate ?? ind.certificate;
  const originHerd =
    typeof ind.origin_herd === "object" ? ind.origin_herd?.herd : null;
  const bought = originHerd && originHerd !== herdNumber ? originHerd : null;
  return (
    <article
      className={`sb-card ${styles["mb-rabbit-card"]}`}
      {...mbPressable(onClick)}
    >
      <MbPhoto ind={ind} />
      <div className={styles["mb-rabbit-card-body"]}>
        <div className="sb-meta">{ind.number}</div>
        <div className={styles["mb-rabbit-name"]}>
          {ind.name || `Kanin ${ind.number}`}
        </div>
        <div className={styles["mb-chip-row"]}>
          <MbSex sex={ind.sex} />
          <span className={styles["mb-age"]}>{mbAge(ind.birth_date)}</span>
        </div>
        <div className={styles["mb-chip-row"]} style={{ marginTop: 8 }}>
          <MbStatus status={status} />
          {cert != null && (
            <span
              className={`sb-badge${digital ? " sb-badge-skog" : ""}`}
              title={
                digital
                  ? "Digitalt intyg — verifierbart i systemet"
                  : "Pappersintyg"
              }
            >
              {digital ? "✓ " : ""}Intyg {cert}
            </span>
          )}
          {bought && (
            <span className="sb-badge sb-badge-himmel">Köpt · {bought}</span>
          )}
          {ind.castration_date && <span className="sb-badge">Kastrerad</span>}
        </div>
        {(ind.mother?.number || ind.father?.number) && (
          <div className={`sb-meta ${styles["mb-parents"]}`}>
            M {ind.mother?.number || "—"} · F {ind.father?.number || "—"}
          </div>
        )}
      </div>
    </article>
  );
}

export default function KaninerTab({
  individuals,
  herdNumber,
  genebankId,
}: KaninerTabProps) {
  const router = useRouter();
  const { t } = useTranslation();
  const [addOpen, setAddOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<KaninFilter>("active");
  const [view, setView] = useState<KaninView>("cards");

  // Persisted view preference (handoff README).
  // Read in an effect: this component never renders on the server (the
  // orchestrator's hydration gate), but the first client render must match
  // the (empty) SSR tree anyway.
  useEffect(() => {
    const stored = window.localStorage.getItem(VIEW_STORAGE_KEY);
    if (stored === "list" || stored === "cards") setView(stored);
  }, []);

  const changeView = (v: KaninView) => {
    setView(v);
    window.localStorage.setItem(VIEW_STORAGE_KEY, v);
  };

  const counts = useMemo(
    () => ({
      all: individuals.length,
      active: individuals.filter((i) => rabbitStatus(i) === "Aktiv").length,
      cert: individuals.filter(hasCert).length,
    }),
    [individuals],
  );

  const list = useMemo(
    () =>
      individuals.filter((r) => {
        if (filter === "active" && rabbitStatus(r) !== "Aktiv") return false;
        if (filter === "cert" && !hasCert(r)) return false;
        const q = search.trim().toLowerCase();
        if (
          q &&
          !(r.number || "").toLowerCase().includes(q) &&
          !(r.name || "").toLowerCase().includes(q)
        ) {
          return false;
        }
        return true;
      }),
    [individuals, search, filter],
  );

  const goTo = (ind: Individual) =>
    router.push(`/stamboken/individ/${encodeURIComponent(ind.number || "")}`);

  const filterChips: [KaninFilter, string][] = [
    ["active", `Aktiva (${counts.active})`],
    ["all", `Alla (${counts.all})`],
    ["cert", `Med intyg (${counts.cert})`],
  ];

  return (
    <div>
      <div
        className={styles["mb-toolbar"]}
        style={{ justifyContent: "flex-end" }}
      >
        <button
          type="button"
          className="sb-btn sb-btn-sm"
          onClick={() => setAddOpen(true)}
        >
          {t("addRabbit.shortcutButton")}
        </button>
      </div>

      <div className={styles["mb-toolbar"]}>
        <input
          className={`sb-input ${styles["mb-search"]}`}
          placeholder="Sök nummer eller namn…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Sök nummer eller namn"
        />
        <div className={styles["mb-view-toggle"]} role="group" aria-label="Vy">
          <button
            type="button"
            className={view === "cards" ? styles["is-active"] : ""}
            onClick={() => changeView("cards")}
          >
            Kort
          </button>
          <button
            type="button"
            className={view === "list" ? styles["is-active"] : ""}
            onClick={() => changeView("list")}
          >
            Lista
          </button>
        </div>
      </div>

      <div className={styles["mb-filter-row"]}>
        {filterChips.map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`${styles["mb-herd-chip"]}${
              filter === id ? ` ${styles["is-active"]}` : ""
            }`}
            onClick={() => setFilter(id)}
          >
            {label}
          </button>
        ))}
        <span className="sb-meta" style={{ marginLeft: "auto" }}>
          {list.length} av {counts.all}
        </span>
      </div>

      {view === "cards" ? (
        <div className={styles["mb-grid-cards"]}>
          {list.map((r) => (
            <MbRabbitCard
              key={r.number}
              ind={r}
              herdNumber={herdNumber}
              onClick={() => goTo(r)}
            />
          ))}
        </div>
      ) : (
        <div
          className={`sb-card ${styles["mb-list"]}`}
          style={{ overflow: "hidden" }}
        >
          {list.map((r) => (
            <MbRabbitRow key={r.number} ind={r} onClick={() => goTo(r)} />
          ))}
        </div>
      )}

      {list.length === 0 && (
        <div className={styles["mb-empty"]}>
          Inga kaniner matchar — prova att ändra filter eller sökning.
        </div>
      )}

      {addOpen && (
        <RegisterRabbitDialog
          open
          onClose={() => setAddOpen(false)}
          herdId={herdNumber}
          genebankId={genebankId}
        />
      )}
    </div>
  );
}
