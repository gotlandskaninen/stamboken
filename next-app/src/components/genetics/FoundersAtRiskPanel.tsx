import React, { useState } from "react";
import Link from "next/link";

import {
  Card,
  CardContent,
  Typography,
  Table,
  TableContainer,
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

const ORDER: FounderAtRisk["risk_level"][] = [
  "critical",
  "warning",
  "monitor",
  "ok",
  "lost",
];

// Action first: 1 bärare kvar, then Ingen bärare with possible carriers to look for, 2–3 bärare
// and Liten andel. Ok, and Ingen bärare with nobody to look for, are folded away.
const rank = (f: FounderAtRisk) =>
  ({
    critical: 0,
    lost: f.recoverable_carriers?.length ? 1 : 5,
    warning: 2,
    monitor: 3,
    ok: 4,
  })[f.risk_level];
export const isFolded = (f: FounderAtRisk) => rank(f) >= 4;

export const founderOrder = (founders: FounderAtRisk[]) =>
  [...founders].sort((a, b) => rank(a) - rank(b));

export const FOUNDER_TABLE_ID = "founderdjurens-lage";

const RabbitLinks = ({ numbers }: { numbers: string[] }) =>
  numbers.map((n, i) => (
    <React.Fragment key={n}>
      {i > 0 && ", "}
      <Link
        href={`/stamboken/individ/${encodeURIComponent(n)}`}
        className="sb-link"
      >
        {n}
      </Link>
    </React.Fragment>
  ));

function CarrierInfo({ founder }: { founder: FounderAtRisk }) {
  const { carrier_ids, recoverable_carriers, risk_level } = founder;

  const parts: React.ReactNode[] = [];

  // Carriers in the calculation (sent for 1 and 2–3 carriers)
  if (carrier_ids.length > 0) {
    parts.push(
      <React.Fragment key="carriers">
        I beräkningen: <RabbitLinks numbers={carrier_ids} />
      </React.Fragment>,
    );
  }

  // recovery_eligible minus the members: certified, no death date or note, not castrated,
  // within the age cap, but outside the calculation (sent for none and 1 carrier)
  if (recoverable_carriers && recoverable_carriers.length > 0) {
    const n = recoverable_carriers.length;
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
        : <RabbitLinks numbers={recoverable_carriers.slice(0, 10)} />
        {n > 10 && ` (+${n - 10} till)`}
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
  const [showAll, setShowAll] = useState(false);

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
  const hidden = founders.filter(isFolded);
  const hiddenOk = hidden.filter((f) => f.risk_level === "ok").length;
  const hiddenParts = [
    hiddenOk && `${riskConfig.ok.label} (${hiddenOk})`,
    hidden.length - hiddenOk &&
      `${riskConfig.lost.label} (${hidden.length - hiddenOk})`,
  ].filter(Boolean);
  const rows = founderOrder(founders).filter((f) => showAll || !isFolded(f));

  return (
    // scrollMarginTop: the link from Läget lands below the sticky top bar.
    // tabIndex: "Se vilka" moves focus here, as a followed in-page link would.
    <Card
      id={FOUNDER_TABLE_ID}
      tabIndex={-1}
      sx={{ mb: 6, scrollMarginTop: 96 }}
    >
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
          {ORDER.filter((level) => counts[level] > 0)
            .map((level) => `${counts[level]} ${riskConfig[level].summary}`)
            .join(" · ")}
        </Typography>
        {rows.length === 0 ? (
          <Typography variant="body2">
            Inget founderdjur behöver åtgärdas just nu.
          </Typography>
        ) : (
          <>
            <Typography
              variant="body2"
              color="textSecondary"
              sx={{ display: { xs: "block", sm: "none" }, mb: 1 }}
            >
              Tabellen är bredare än skärmen. Dra i sidled för att se alla
              kolumner.
            </Typography>
            <TableContainer>
              <Table size="small" sx={{ minWidth: 640 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Founderdjur</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell align="right">Bärare i beräkningen</TableCell>
                    <TableCell align="right">Andel av generna</TableCell>
                    {hasRetention && (
                      <TableCell align="right">
                        Bevarade gener (simulerat)
                      </TableCell>
                    )}
                    <TableCell>Bärare</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((f) => {
                    const config = riskConfig[f.risk_level];
                    return (
                      <TableRow key={f.founder_id}>
                        <TableCell sx={{ whiteSpace: "nowrap" }}>
                          <RabbitLinks numbers={[f.founder_id]} />
                        </TableCell>
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
            </TableContainer>
          </>
        )}
        {hidden.length > 0 && (
          <button
            type="button"
            className="sb-btn sb-btn-sm sb-btn-secondary"
            style={{ marginTop: 16 }}
            aria-expanded={showAll}
            onClick={() => setShowAll(!showAll)}
          >
            {showAll
              ? `Dölj de ${hidden.length}`
              : `Visa ${hidden.length} till: ${hiddenParts.join(" och ")}`}
          </button>
        )}
      </CardContent>
    </Card>
  );
};

export default FoundersAtRiskPanel;
