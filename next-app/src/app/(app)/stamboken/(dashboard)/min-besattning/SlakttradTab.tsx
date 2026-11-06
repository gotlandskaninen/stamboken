"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { skipToken } from "@reduxjs/toolkit/query";
import {
  useGetIndividualPedigreeQuery,
  type Individual,
  type PedigreeNode,
} from "@/redux/api/apiSlice";
import { MbCard, MbSex, rabbitStatus } from "./min-besattning-ui";
import styles from "./min-besattning.module.css";

interface SlakttradTabProps {
  individuals: Individual[];
}

/* Parent / grandparent node — prototype Node, page.jsx lines 295-304.
   The node comes from the pedigree endpoint, so "Okänd" (dashed) means the
   database genuinely lacks the ancestor — not merely that it is off-herd. */
function PedNode({ role, ind }: { role: string; ind: PedigreeNode | null }) {
  const known = ind != null && !!ind.number;
  return (
    <div
      className={`${styles["mb-ped-node"]}${
        known ? ` ${styles["is-known"]}` : ""
      }`}
    >
      <span className="sb-stat-label" style={{ marginTop: 0 }}>
        {role}
      </span>
      <span className="sb-meta" style={{ color: "var(--sb-ink)" }}>
        {ind?.number || "Okänd"}
      </span>
      {ind?.name && <span className={styles["mb-ped-name"]}>{ind.name}</span>}
    </div>
  );
}

export default function SlakttradTab({ individuals }: SlakttradTabProps) {
  // Herd lookup by genbank number — resolves the selected (self) animal.
  const byNumber = useMemo(() => {
    const m = new Map<string, Individual>();
    for (const i of individuals) if (i.number) m.set(i.number, i);
    return m;
  }, [individuals]);

  // Picker: active animals first, else the whole herd (prototype uses the
  // active subset; empty herds must still render something pickable).
  const pickable = useMemo(() => {
    const active = individuals.filter((i) => rabbitStatus(i) === "Aktiv");
    return active.length > 0 ? active : individuals;
  }, [individuals]);

  const [selectedNumber, setSelectedNumber] = useState<string | null>(
    pickable[0]?.number ?? null,
  );

  const selected =
    (selectedNumber ? byNumber.get(selectedNumber) : null) ??
    pickable[0] ??
    null;

  // Ancestors come from the existing pedigree endpoint (generations=3 =
  // self + parents + grandparents), so off-herd ancestors resolve too.
  const {
    data: pedigree,
    isFetching,
    isError,
  } = useGetIndividualPedigreeQuery(selected?.number ?? skipToken);

  if (!selected) {
    return (
      <div className={styles["mb-empty"]}>
        Inga kaniner i besättningen att visa släktträd för.
      </div>
    );
  }

  return (
    <div className={`${styles["mb-two-col"]} ${styles["mb-two-col-rev"]}`}>
      <div className={styles["mb-col-side"]}>
        <MbCard title="Välj kanin" pad={false}>
          <div className={styles["mb-list"]}>
            {pickable.map((x) => (
              <button
                key={x.number}
                type="button"
                className={`${styles["mb-ped-pick"]}${
                  x.number === selected.number ? ` ${styles["is-active"]}` : ""
                }`}
                onClick={() => setSelectedNumber(x.number)}
              >
                <span className="sb-meta">{x.number}</span>{" "}
                {x.name || `Kanin ${x.number}`}
              </button>
            ))}
          </div>
        </MbCard>
      </div>

      <div className={styles["mb-col-main"]}>
        <MbCard title={`Släktträd — ${selected.name || selected.number}`}>
          {isFetching ? (
            <div
              className="sb-placeholder"
              style={{ minHeight: 220, borderRadius: "var(--sb-r-2)" }}
              role="status"
            >
              Laddar släktträd…
            </div>
          ) : isError ? (
            <p className="sb-meta">Kunde inte hämta släktträdet just nu.</p>
          ) : (
            <div className={styles["mb-ped"]}>
              <div className={styles["mb-ped-col"]}>
                <div
                  className={`${styles["mb-ped-node"]} ${styles["is-self"]}`}
                >
                  <span className="sb-meta" style={{ color: "var(--sb-ink)" }}>
                    {selected.number}
                  </span>
                  <span
                    className={styles["mb-ped-name"]}
                    style={{ fontSize: 18 }}
                  >
                    {selected.name || `Kanin ${selected.number}`}
                  </span>
                  <MbSex sex={selected.sex} />
                </div>
              </div>
              <div className={styles["mb-ped-col"]}>
                <PedNode role="Mor" ind={pedigree?.mother ?? null} />
                <PedNode role="Far" ind={pedigree?.father ?? null} />
              </div>
              <div className={styles["mb-ped-col"]}>
                <PedNode role="Mormor" ind={pedigree?.mother?.mother ?? null} />
                <PedNode role="Morfar" ind={pedigree?.mother?.father ?? null} />
                <PedNode role="Farmor" ind={pedigree?.father?.mother ?? null} />
                <PedNode role="Farfar" ind={pedigree?.father?.father ?? null} />
              </div>
            </div>
          )}
          <p className="sb-meta" style={{ marginTop: 16 }}>
            <Link
              href={`/stamboken/individ/${encodeURIComponent(
                selected.number || "",
              )}`}
              className="sb-link"
            >
              Fullständig stamtavla med inavelskoefficient finns på
              individsidan.
            </Link>
          </p>
        </MbCard>
      </div>
    </div>
  );
}
