import React from "react";

import {
  Card,
  CardContent,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Chip,
  Skeleton,
} from "@mui/material";

import {
  useFetchFoundersAtRiskQuery,
  FounderAtRisk,
} from "@/redux/api/apiSlice";
import { useQueryView, StaleNote } from "./queryView";
import { useMode } from "@/lib/mode-context";
import { percent } from "@/lib/genetics";
import GeneticsError from "./GeneticsError";
import { FOUNDERDJUR } from "./GeneticsInfoPanel";
import { readableChip } from "./readableChip";

// The levels follow identify_founders_at_risk (genetics.py): carriers among the
// rabbits in the calculation, and "liten andel" below half an equal share.
const riskConfig: Record<
  FounderAtRisk["risk_level"],
  {
    label: string;
    summary: string;
    color: "error" | "warning" | "info" | "success" | "default";
  }
> = {
  lost: { label: "Ingen bärare", summary: "utan bärare", color: "default" },
  critical: {
    label: "1 bärare kvar",
    summary: "med 1 bärare kvar",
    color: "error",
  },
  warning: { label: "2–3 bärare", summary: "med 2–3 bärare", color: "warning" },
  monitor: {
    label: "Liten andel",
    summary: "med liten andel av generna",
    color: "info",
  },
  ok: { label: "Ok", summary: "ok", color: "success" },
};

function CarrierInfo({ founder }: { founder: FounderAtRisk }) {
  const { carrier_ids, recoverable_carriers, risk_level } = founder;

  const parts: React.ReactNode[] = [];

  // Carriers in the calculation (sent for 1 and 2–3 carriers)
  if (carrier_ids.length > 0) {
    parts.push(`I beräkningen: ${carrier_ids.join(", ")}`);
  }

  // recovery_eligible minus the members: certified, no death date or note, not castrated,
  // within the age cap, but outside the calculation (sent for none and 1 carrier)
  if (recoverable_carriers && recoverable_carriers.length > 0) {
    const n = recoverable_carriers.length;
    const label =
      n <= 10
        ? recoverable_carriers.join(", ")
        : `${recoverable_carriers.slice(0, 10).join(", ")} (+${n - 10} till)`;
    parts.push(
      <Typography
        key="recoverable"
        component="span"
        variant="body2"
        sx={{ color: "info.main", fontStyle: "italic" }}
      >
        {n === 1
          ? "1 kanin utan dödsdatum som inte är med i beräkningen"
          : `${n} kaniner utan dödsdatum som inte är med i beräkningen`}
        : {label}
      </Typography>,
    );
  } else if (risk_level === "lost") {
    parts.push("Inga levande bärare hittades");
  }

  return (
    <>
      {parts.map((part, i) => (
        <React.Fragment key={i}>
          {i > 0 && <br />}
          {part}
        </React.Fragment>
      ))}
    </>
  );
}

interface FoundersAtRiskPanelProps {
  genebankId: number;
}

const FoundersAtRiskPanel = ({ genebankId }: FoundersAtRiskPanelProps) => {
  const mode = useMode();
  const query = useFetchFoundersAtRiskQuery(
    { genebankId, mode },
    {
      refetchOnMountOrArgChange: true,
    },
  );
  const { data: founders, loading, failed, stale } = useQueryView(query);

  if (loading) {
    return <Skeleton variant="rounded" height={200} sx={{ mb: 6 }} />;
  }

  if (failed) {
    // A denial seen by another genetics panel hides this too; it reads as no access.
    return (
      <GeneticsError
        error={query.error ?? { status: 403 }}
        onRetry={query.refetch}
      />
    );
  }

  if (!founders || founders.length === 0) return null;

  const hasRetention = founders.some((f) => f.allele_retention !== null);

  // Summary counts
  const counts = { lost: 0, critical: 0, warning: 0, monitor: 0, ok: 0 };
  for (const f of founders) counts[f.risk_level]++;

  return (
    <Card sx={{ mb: 6 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Founderdjurens läge ({founders.length} founderdjur)
        </Typography>
        <Typography variant="body2" color="textSecondary" sx={{ mb: 1 }}>
          {FOUNDERDJUR} En bärare är en kanin i beräkningen som har gener från
          founderdjuret.
        </Typography>
        {stale && <StaleNote />}
        <Typography
          variant="body2"
          color="textSecondary"
          sx={{
            mb: 4,
          }}
        >
          {(Object.keys(counts) as FounderAtRisk["risk_level"][])
            .filter((level) => counts[level] > 0)
            .map((level) => `${counts[level]} ${riskConfig[level].summary}`)
            .join(" · ")}
        </Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Founderdjur</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Bärare i beräkningen</TableCell>
              <TableCell align="right">Andel av generna</TableCell>
              {hasRetention && (
                <TableCell align="right">Bevarade gener (simulerat)</TableCell>
              )}
              <TableCell>Bärare</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {founders.map((f) => {
              const config = riskConfig[f.risk_level];
              return (
                <TableRow key={f.founder_id}>
                  <TableCell>{f.founder_id}</TableCell>
                  <TableCell>
                    <Chip
                      label={config.label}
                      color={config.color}
                      size="small"
                      sx={readableChip}
                    />
                  </TableCell>
                  <TableCell align="right">{f.n_carriers}</TableCell>
                  <TableCell align="right">
                    {percent(f.avg_contribution, 2)}
                  </TableCell>
                  {hasRetention && (
                    <TableCell align="right">
                      {f.allele_retention !== null
                        ? percent(f.allele_retention)
                        : "–"}
                    </TableCell>
                  )}
                  <TableCell>
                    <Typography variant="body2" color="textSecondary">
                      <CarrierInfo founder={f} />
                    </Typography>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
};

export default FoundersAtRiskPanel;
