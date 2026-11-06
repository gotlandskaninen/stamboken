"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from "@mui/material";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";

const MINUTES = ["1", "5", "15"];
// Adminpanel.html:59 .ad-cell-mono / :60 .ad-cell-dim. Lagda som sx (inte
// modulklass) så att de vinner över temats MuiTableCell-overrides utan
// specificitetsstrid mot emotion.
const MONO_CELL = { fontFamily: "var(--sb-mono)", fontSize: "12.5px" };
const MONO_DIM_CELL = { ...MONO_CELL, color: "var(--sb-ink-3)" };

export function OnlineClient({
  rows,
  minutes,
}: {
  rows: {
    username: string | null; // hbuser.username is nullable
    fullname: string | null;
    last_active: string | null;
  }[];
  minutes: string;
}) {
  const router = useRouter();
  useEffect(() => {
    // Auto-refresh the RSC every 30 s.
    const t = setInterval(() => router.refresh(), 30_000);
    return () => clearInterval(t);
  }, [router]);
  return (
    <>
      <nav aria-label="Tidsperiod" className={styles["ad-pill-row"]}>
        {MINUTES.map((m) => (
          <Link
            key={m}
            href={`?minutes=${m}`}
            aria-current={m === minutes ? "true" : undefined}
            className={
              m === minutes
                ? `${styles["ad-pill"]} ${styles["is-active"]}`
                : styles["ad-pill"]
            }
          >
            {m} min
          </Link>
        ))}
        <span className={`sb-meta ${styles["ad-pill-meta"]}`}>
          Uppdateras automatiskt var 30:e sekund
        </span>
      </nav>
      <div className={`sb-card ${ds["ad-grid"]}`}>
        <TableContainer>
          {/* min-width 720px = handoffens .ad-table (Adminpanel.html:52);
              TableContainer scrollar horisontellt i kortet, aldrig sidan
              (ADR-0010, 375-px-kravet). */}
          <Table size="small" sx={{ minWidth: 720 }}>
            <TableHead>
              <TableRow>
                <TableCell>Användarnamn</TableCell>
                <TableCell>Namn</TableCell>
                <TableCell>Senast aktiv</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r, i) => (
                <TableRow key={r.username ?? i}>
                  <TableCell sx={MONO_CELL}>
                    <span
                      className={styles["ad-online-dot"]}
                      aria-hidden="true"
                    />
                    {r.username || "—"}
                  </TableCell>
                  <TableCell>{r.fullname || "—"}</TableCell>
                  <TableCell sx={MONO_DIM_CELL}>
                    {r.last_active
                      ? new Date(r.last_active).toLocaleString("sv-SE", {
                          timeZone: "Europe/Stockholm",
                        })
                      : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        {rows.length === 0 && (
          <p className={ds["ad-empty-note"]}>
            {Number(minutes) === 1
              ? "Ingen aktivitet den senaste minuten."
              : `Ingen aktivitet de senaste ${minutes} minuterna.`}
          </p>
        )}
      </div>
    </>
  );
}
