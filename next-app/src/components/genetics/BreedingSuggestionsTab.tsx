import React, { useState } from "react";
import { skipToken } from "@reduxjs/toolkit/query";

import {
  Box,
  Button,
  Card,
  Chip,
  Paper,
  Skeleton,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { green } from "@mui/material/colors";

import {
  useFetchBreedingSuggestionsQuery,
  useFetchPopulationMetricsQuery,
  BreedingSuggestionsParams,
} from "@/redux/api/apiSlice";
import HelpTooltip from "./HelpTooltip";
import GeneticsInfoPanel from "./GeneticsInfoPanel";
import { useQueryView } from "./queryView";
import { useMode } from "@/lib/mode-context";
import GeneticsError from "./GeneticsError";
import { translateReasons } from "@/utils/translateReasons";
import { decimal, percent } from "@/lib/genetics";

function getMsiColor(msi: number): "success" | "warning" | "error" {
  if (msi <= 2) return "success";
  if (msi <= 4) return "warning";
  return "error";
}

interface BreedingSuggestionsTabProps {
  genebankId: number;
}

const BASE_MAX_INBREEDING = 0.0625;
const MAX_INBREEDING_LIMIT = 0.25;

const BreedingSuggestionsTab = ({
  genebankId,
}: BreedingSuggestionsTabProps) => {
  const [maxPairs, setMaxPairs] = useState(20);
  // null until the user edits the field: the default follows the breed's
  // expected offspring F under random mating (shared overview query).
  const [editedMaxInbreeding, setMaxInbreeding] = useState<number | null>(null);
  const [maxPerMale, setMaxPerMale] = useState(3);

  const mode = useMode();
  const metricsQuery = useFetchPopulationMetricsQuery(
    { genebankId, mode },
    { refetchOnMountOrArgChange: true },
  );
  const metricsView = useQueryView(metricsQuery);
  // Only a value this visit confirmed: after a failed or denied refresh the
  // expected F is unknown, and the cap falls back to its base.
  const metrics = metricsView.stale ? undefined : metricsView.data;
  // An automatic cap waits for that value; a typed one does not.
  const capPending = editedMaxInbreeding === null && metricsQuery.isFetching;
  const expectedOffspringF = metrics?.expected_offspring_f ?? null;
  // Explicit null from the API: no male or no female in the reference population
  const lacksSexes = metrics != null && metrics.expected_offspring_f === null;
  // Rounded up so the default never falls below the expected offspring F
  const maxInbreeding =
    editedMaxInbreeding ??
    Math.min(
      Math.max(
        BASE_MAX_INBREEDING,
        Math.ceil((expectedOffspringF ?? 0) * 10000) / 10000,
      ),
      MAX_INBREEDING_LIMIT,
    );

  // Only fetch when user clicks "Beräkna"; a mode switch drops the calculation
  // made in the other mode, so its pairs are never shown in this one.
  const [requestedParams, setQueryParams] =
    useState<BreedingSuggestionsParams | null>(null);
  const queryParams = requestedParams?.mode === mode ? requestedParams : null;

  // Every "Beräkna" asks the server: a cached answer may be one a denial hides.
  const suggestionsQuery = useFetchBreedingSuggestionsQuery(
    queryParams ?? skipToken,
    { refetchOnMountOrArgChange: true },
  );
  const { isLoading, isFetching, error } = suggestionsQuery;
  const suggestionsView = useQueryView(suggestionsQuery);
  // Only the answer for the submitted parameters (the view reads currentData), and nothing on an error.
  const suggestions = error ? undefined : suggestionsView.data;

  const usedCap = queryParams?.maxInbreeding ?? maxInbreeding;
  const raiseHint =
    usedCap < MAX_INBREEDING_LIMIT ? " Höj taket för att få förslag." : "";
  // Loaded null: no male or female. Loaded value: the cap is the cause.
  // Unknown (metrics loading or failed): neutral, no claim about the cause.
  const emptyMessage = lacksSexes
    ? "Referenspopulationen saknar hanar eller honor, så inga par kan föreslås."
    : expectedOffspringF != null
      ? `Inga par klarar taket ${percent(usedCap)}. Förväntad inavel vid slumpparning i rasen är ${percent(expectedOffspringF)}.${raiseHint}`
      : `Inga par hittades under taket ${percent(usedCap)}.${raiseHint}`;

  const handleCalculate = () => {
    const params = { genebankId, mode, maxPairs, maxInbreeding, maxPerMale };
    if (JSON.stringify(params) === JSON.stringify(queryParams))
      suggestionsQuery.refetch(); // the same calculation again
    else setQueryParams(params);
  };

  return (
    <Box>
      <GeneticsInfoPanel tab="breeding" />
      <Card sx={{ mb: 6, p: 4 }}>
        <Box
          sx={{
            display: "flex",
            gap: 2,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <TextField
            label="Max antal par"
            type="number"
            size="small"
            value={maxPairs}
            onChange={(e) =>
              setMaxPairs(Math.min(Math.max(Number(e.target.value), 1), 50))
            }
            slotProps={{ htmlInput: { min: 1, max: 50 } }}
            sx={{ width: 140 }}
          />
          <TextField
            label="Max inavel (F)"
            type="number"
            size="small"
            value={maxInbreeding}
            onChange={(e) =>
              setMaxInbreeding(
                Math.min(
                  Math.max(Number(e.target.value), 0),
                  MAX_INBREEDING_LIMIT,
                ),
              )
            }
            slotProps={{ htmlInput: { min: 0, max: 0.25, step: 0.005 } }}
            sx={{ width: 140 }}
          />
          <TextField
            label="Max per hane"
            type="number"
            size="small"
            value={maxPerMale}
            onChange={(e) =>
              setMaxPerMale(Math.min(Math.max(Number(e.target.value), 1), 10))
            }
            slotProps={{ htmlInput: { min: 1, max: 10 } }}
            sx={{ width: 140 }}
          />
          <Button
            variant="contained"
            onClick={handleCalculate}
            disabled={isFetching || capPending}
          >
            {isFetching ? "Beräknar..." : "Beräkna"}
          </Button>
        </Box>
      </Card>

      {isFetching && (
        <Alert severity="info" sx={{ mb: 4 }}>
          Beräknar parningsförslag — detta kan ta upp till en minut beroende på
          populationsstorlek.
        </Alert>
      )}

      {isLoading && <Skeleton variant="rounded" height={400} />}

      {(error || (suggestionsView.denied && !isFetching)) && (
        <GeneticsError
          error={error ?? { status: 403 }}
          onRetry={() => suggestionsQuery.refetch()}
        />
      )}

      {suggestions && suggestions.length === 0 && (
        <Alert severity="info">{emptyMessage}</Alert>
      )}

      {suggestions && suggestions.length > 0 && (
        <Card sx={{ mb: 6 }}>
          <Paper>
            <Box
              sx={{
                overflowY: "auto",
                maxWidth: (theme) => `calc(100vw - ${theme.spacing(12)})`,
              }}
            >
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>#</TableCell>
                    <TableCell>Hane</TableCell>
                    <TableCell>Hona</TableCell>
                    <TableCell align="right">
                      <HelpTooltip tooltip="Förväntad inavelskoefficient hos avkomma. Lika med kinship mellan föräldrarna.">
                        Förväntad F
                      </HelpTooltip>
                    </TableCell>
                    <TableCell align="right">
                      <HelpTooltip tooltip="Förändring i gendiversitet om paret paras. Positivt = förbättring.">
                        ΔGD
                      </HelpTooltip>
                    </TableCell>
                    <TableCell align="center">
                      <HelpTooltip tooltip="Mate Suitability Index (1–6). 1 = utmärkt, 6 = dålig. Baserat på Pollak et al. (PMx).">
                        MSI
                      </HelpTooltip>
                    </TableCell>
                    <TableCell>Skäl</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {suggestions.map((s, index) => (
                    <TableRow key={`${s.sire_id}-${s.dam_id}`}>
                      <TableCell>{index + 1}</TableCell>
                      <TableCell>{s.sire_id}</TableCell>
                      <TableCell>{s.dam_id}</TableCell>
                      <TableCell align="right">
                        {percent(s.expected_f, 2)}
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: s.delta_gd > 0 ? green[600] : "inherit" }}
                      >
                        {decimal(s.delta_gd, 4)}
                      </TableCell>
                      <TableCell align="center">
                        <Chip
                          label={s.mate_suitability_index}
                          color={getMsiColor(s.mate_suitability_index)}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" color="textSecondary">
                          {translateReasons(s.reasons).join("; ")}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Paper>
        </Card>
      )}

      {!queryParams && !isLoading && (
        <Alert severity="info">
          Klicka &quot;Beräkna&quot; för att generera parningsförslag.
        </Alert>
      )}
    </Box>
  );
};

export default BreedingSuggestionsTab;
