import React from "react";
import { Box, Card, CardContent, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import WarningIcon from "@mui/icons-material/Warning";
import ErrorIcon from "@mui/icons-material/Error";

import type { FounderAtRisk, PopulationMetrics } from "@/redux/api/apiSlice";
import { decimal, percent } from "@/lib/genetics";
import { FOUNDER_TABLE_ID } from "./FoundersAtRiskPanel";

type Level = "good" | "warning" | "danger";

export interface LageLine {
  level: Level;
  text: string;
  anchor?: string; // links "Se vilka" to this element id
}

/** The page's verdict in a few short lines, banded on each value as shown. */
export function lageLines(
  metrics: PopulationMetrics,
  founders?: FounderAtRisk[],
): LageLine[] {
  if (metrics.n_active === 0) return [];
  const lines: LageLine[] = [];

  const ne = metrics.effective_population_size;
  if (ne != null) {
    const n = Math.round(ne);
    lines.push(
      n >= 100
        ? { level: "good", text: `Ne är ${decimal(ne)}. Det når målet 100.` }
        : n >= 50
          ? {
              level: "warning",
              text: `Ne är ${decimal(ne)}. Det är över FAO:s gräns 50 men under målet 100.`,
            }
          : {
              level: "danger",
              text: `Ne är ${decimal(ne)}. Det är under FAO:s gräns 50.`,
            },
    );
  }

  const df = metrics.delta_f;
  if (df != null) {
    const shown = Number((df * 100).toFixed(2));
    lines.push(
      shown <= 0
        ? { level: "good", text: "Inaveln ökar inte per generation." }
        : shown < 1
          ? {
              level: "good",
              text: `Inaveln ökar ${percent(df, 2)} per generation, under FAO:s gräns 1 %.`,
            }
          : {
              level: "danger",
              text: `Inaveln ökar ${percent(df, 2)} per generation. FAO:s gräns är 1 %.`,
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
                    <a className="sb-link" href={`#${line.anchor}`}>
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
