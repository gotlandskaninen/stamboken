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
  Alert,
} from "@mui/material";

import {
  useFetchFoundersAtRiskQuery,
  FounderAtRisk,
} from "@/redux/api/apiSlice";

const riskConfig: Record<
  FounderAtRisk["risk_level"],
  { label: string; color: "error" | "warning" | "info" | "success" | "default" }
> = {
  lost: { label: "Förlorad", color: "default" },
  critical: { label: "Kritisk", color: "error" },
  warning: { label: "Varning", color: "warning" },
  monitor: { label: "Bevaka", color: "info" },
  ok: { label: "Ok", color: "success" },
};

function CarrierInfo({ founder }: { founder: FounderAtRisk }) {
  const { carrier_ids, recoverable_carriers, risk_level, n_carriers } = founder;

  const parts: React.ReactNode[] = [];

  // Active carriers (shown for critical/warning)
  if (carrier_ids.length > 0) {
    parts.push(carrier_ids.join(", "));
  } else if (risk_level === "monitor" || risk_level === "ok") {
    parts.push(`${n_carriers} aktiva`);
  }

  // Recoverable carriers (shown for lost/critical)
  if (recoverable_carriers && recoverable_carriers.length > 0) {
    const label =
      recoverable_carriers.length <= 10
        ? recoverable_carriers.join(", ")
        : `${recoverable_carriers.slice(0, 10).join(", ")} (+${recoverable_carriers.length - 10} till)`;
    parts.push(
      <Typography
        key="recoverable"
        component="span"
        variant="body2"
        sx={{ color: "info.main", fontStyle: "italic" }}
      >
        {recoverable_carriers.length} inaktiv(a) utan dödsdatum: {label}
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
  const {
    data: founders,
    isLoading,
    error,
  } = useFetchFoundersAtRiskQuery(genebankId);

  if (isLoading) {
    return <Skeleton variant="rounded" height={200} sx={{ mb: 6 }} />;
  }

  const isAuthError =
    error != null &&
    typeof error === "object" &&
    "status" in error &&
    (error as { status: unknown }).status === 401;

  if (error && !isAuthError) {
    return (
      <Alert severity="error" sx={{ mb: 6 }}>
        Kunde inte hämta data om founders.
      </Alert>
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
          Founder-status ({founders.length} founders)
        </Typography>
        <Typography
          variant="body2"
          color="textSecondary"
          sx={{
            mb: 4,
          }}
        >
          {counts.lost > 0 && `${counts.lost} förlorade · `}
          {counts.critical > 0 && `${counts.critical} kritiska · `}
          {counts.warning > 0 && `${counts.warning} varning · `}
          {counts.monitor > 0 && `${counts.monitor} bevaka · `}
          {counts.ok} ok
        </Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Founder</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Aktiva bärare</TableCell>
              <TableCell align="right">Bidrag (%)</TableCell>
              {hasRetention && (
                <TableCell align="right">Allelretention</TableCell>
              )}
              <TableCell>Detaljer</TableCell>
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
                    />
                  </TableCell>
                  <TableCell align="right">{f.n_carriers}</TableCell>
                  <TableCell align="right">
                    {(f.avg_contribution * 100).toFixed(2)}%
                  </TableCell>
                  {hasRetention && (
                    <TableCell align="right">
                      {f.allele_retention !== null
                        ? `${(f.allele_retention * 100).toFixed(1)}%`
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
