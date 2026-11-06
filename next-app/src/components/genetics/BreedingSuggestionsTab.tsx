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
import { translateReasons } from "@/utils/translateReasons";

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

const formatPercent = (value: number) => `${(value * 100).toFixed(1)} %`;

const BreedingSuggestionsTab = ({
  genebankId,
}: BreedingSuggestionsTabProps) => {
  const [maxPairs, setMaxPairs] = useState(20);
  // null until the user edits the field: the default follows the breed's
  // expected offspring F under random mating (shared overview query).
  const [editedMaxInbreeding, setMaxInbreeding] = useState<number | null>(null);
  const [maxPerMale, setMaxPerMale] = useState(3);

  const { data: metrics } = useFetchPopulationMetricsQuery(genebankId);
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

  // Only fetch when user clicks "Beräkna"
  const [queryParams, setQueryParams] =
    useState<BreedingSuggestionsParams | null>(null);

  const {
    data: suggestions,
    isLoading,
    isFetching,
    error,
  } = useFetchBreedingSuggestionsQuery(queryParams ?? skipToken);

  const usedCap = queryParams?.maxInbreeding ?? maxInbreeding;
  const raiseHint =
    usedCap < MAX_INBREEDING_LIMIT ? " Höj taket för att få förslag." : "";
  // Loaded null: no male or female. Loaded value: the cap is the cause.
  // Unknown (metrics loading or failed): neutral, no claim about the cause.
  const emptyMessage = lacksSexes
    ? "Referenspopulationen saknar hanar eller honor, så inga par kan föreslås."
    : expectedOffspringF != null
      ? `Inga par klarar taket ${formatPercent(usedCap)}. Förväntad inavel vid slumpparning i rasen är ${formatPercent(expectedOffspringF)}.${raiseHint}`
      : `Inga par hittades under taket ${formatPercent(usedCap)}.${raiseHint}`;

  const handleCalculate = () => {
    setQueryParams({
      genebankId,
      maxPairs,
      maxInbreeding,
      maxPerMale,
    });
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
            disabled={isFetching}
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

      {error &&
        !(
          typeof error === "object" &&
          "status" in error &&
          (error as { status: unknown }).status === 401
        ) && (
          <Alert severity="error">
            Kunde inte beräkna parningsförslag. Kontrollera att genbanken har
            tillräckligt med aktiva individer med könsdata.
          </Alert>
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
                        {(s.expected_f * 100).toFixed(2)}%
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: s.delta_gd > 0 ? green[600] : "inherit" }}
                      >
                        {s.delta_gd.toFixed(4)}
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
                          {translateReasons(s.reasons).join(", ")}
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
