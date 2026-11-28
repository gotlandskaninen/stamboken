import React from "react";
import { Box, Card, CardContent, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import WarningIcon from "@mui/icons-material/Warning";
import ErrorIcon from "@mui/icons-material/Error";

import type { FounderAtRisk, PopulationMetrics } from "@/redux/api/apiSlice";
import { decimal } from "@/lib/genetics";
import { FOUNDER_TABLE_ID } from "./FoundersAtRiskPanel";

type Level = "good" | "warning" | "danger";

export interface LageLine {
  level: Level;
  text: string;
  anchor?: string; // links "Se vilka" to this element id
}

const neLevel = (ne: number): Level =>
  ne >= 100 ? "good" : ne >= 50 ? "warning" : "danger";
// ΔF in percent. Ne = 1/(2·ΔF), so ΔF at most 1 % is the same as Ne at least 50.
const dfLevel = (pct: number): Level => (pct <= 1 ? "good" : "danger");

// Banded on the unrounded value; the number gets another decimal while rounding would cross a limit.
function shown(x: number, digits: number, level: (v: number) => Level) {
  while (digits < 4 && level(Number(x.toFixed(digits))) !== level(x)) digits++;
  return decimal(x, digits);
}

/** The page's verdict in a few short lines. */
export function lageLines(
  metrics: PopulationMetrics,
  founders?: FounderAtRisk[],
): LageLine[] {
  if (metrics.n_active === 0) return [];
  const lines: LageLine[] = [];

  const ne = metrics.effective_population_size;
  if (ne != null) {
    const n = shown(ne, 0, neLevel);
    const text = {
      good: `Ne är ${n}, minst 100 som är målet.`,
      warning: `Ne är ${n}, minst 50 som FAO anger men under målet 100.`,
      danger: `Ne är ${n}, under 50 som FAO anger.`,
    };
    lines.push({ level: neLevel(ne), text: text[neLevel(ne)] });
  }

  const df = metrics.delta_f;
  if (df != null) {
    const pct = df * 100;
    const p = `${shown(pct, 2, dfLevel)}\u00a0%`;
    lines.push(
      df <= 0
        ? { level: "good", text: "Inaveln ökar inte per generation." }
        : dfLevel(pct) === "good"
          ? {
              level: "good",
              text: `Inaveln ökar ${p} per generation, högst 1\u00a0% som FAO anger.`,
            }
          : {
              level: "danger",
              text: `Inaveln ökar ${p} per generation, mer än 1\u00a0% som FAO anger.`,
            },
    );
  }

  if (founders) {
    const one = founders.filter((f) => f.risk_level === "critical").length;
    lines.push(
      one > 0
        ? {
            level: "danger",
            text: `${one} founderdjur har bara 1 bärare kvar.`,
            anchor: FOUNDER_TABLE_ID,
          }
        : {
            level: "good",
            text: "Inget founderdjur har bara 1 bärare kvar.",
          },
    );
    // Only when there is something to do: rabbits outside the calculation that may carry the genes.
    const lookFor = founders.filter(
      (f) => f.risk_level === "lost" && f.recoverable_carriers?.length,
    ).length;
    if (lookFor > 0) {
      lines.push({
        level: "warning",
        text: `${lookFor} founderdjur saknar bärare i beräkningen, men det finns möjliga bärare att leta upp.`,
        anchor: FOUNDER_TABLE_ID,
      });
    }
  }
  return lines;
}

// Shape and a spoken word carry the level, not the colour alone.
const marks: Record<Level, React.ReactNode> = {
  good: (
    <CheckCircleIcon titleAccess="Bra" sx={{ color: "var(--sb-success)" }} />
  ),
  warning: (
    <WarningIcon titleAccess="Bevaka" sx={{ color: "var(--sb-warning)" }} />
  ),
  danger: (
    <ErrorIcon titleAccess="Åtgärda" sx={{ color: "var(--sb-danger)" }} />
  ),
};

interface LagetProps {
  metrics: PopulationMetrics;
  founders?: FounderAtRisk[];
}

const Laget = ({ metrics, founders }: LagetProps) => {
  const lines = lageLines(metrics, founders);
  if (lines.length === 0) return null;
  return (
    <Card sx={{ mb: 6 }}>
      <CardContent>
        <Typography variant="h6" component="h2" gutterBottom>
          Läget
        </Typography>
        <Box
          component="ul"
          sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 2 }}
        >
          {lines.map((line) => (
            <Box
              component="li"
              key={line.text}
              sx={{ display: "flex", gap: 2, alignItems: "flex-start" }}
            >
              {marks[line.level]}
              <Typography variant="body1">
                {line.text}
                {line.anchor && (
                  <>
                    {" "}
                    <a
                      className="sb-link"
                      href={`#${line.anchor}`}
                      onClick={(e) => {
                        // No history entry: Back must leave the page as it was,
                        // and Next does not restore its URL state from a hash entry.
                        e.preventDefault();
                        const target = document.getElementById(line.anchor!);
                        target?.scrollIntoView({ block: "start" });
                        target?.focus({ preventScroll: true });
                      }}
                    >
                      Se vilka
                    </a>
                  </>
                )}
              </Typography>
            </Box>
          ))}
        </Box>
      </CardContent>
    </Card>
  );
};

export default Laget;
