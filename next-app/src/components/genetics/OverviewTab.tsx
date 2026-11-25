import React from "react";
import { withTheme } from "@emotion/react";
import dynamic from "next/dynamic";

import {
  Box,
  Grid,
  Card,
  CardContent,
  Typography,
  Skeleton,
  Alert,
  List,
  ListItem,
  ListItemText,
} from "@mui/material";

import {
  useFetchPopulationMetricsQuery,
  useFetchFounderStatisticsQuery,
  useFetchFoundersAtRiskQuery,
  useFetchGeneticsTrendsQuery,
  type TrendDataPoint,
} from "@/redux/api/apiSlice";
import { decimal, percent } from "@/lib/genetics";
import KpiCard from "./KpiCard";
import GeneticsInfoPanel, {
  FOUNDERDJUR,
  IN_CALCULATION,
  MK_TEXT,
} from "./GeneticsInfoPanel";
import GeneticsError from "./GeneticsError";
import TrendChart from "./TrendChart";
import FoundersAtRiskPanel from "./FoundersAtRiskPanel";
import Laget from "./Laget";
import type { Theme } from "@mui/material/styles";

const Chart = dynamic(() => import("react-apexcharts"), {
  ssr: false,
});

// No literature gives an absolute MK threshold (FAO 2023: kinship rises with pedigree
// knowledge), so no level is coloured. The comparison is the two latest closed years, both on
// the history rule: today's set is another population and does not compare with them.
function closedYearsMk(trend: TrendDataPoint[]): string {
  const years = trend.slice(-2);
  if (years.length === 0) return "stängda år: –";
  const shown = years.map(
    (d) =>
      `${d.year}: ${d.mean_kinship == null ? "–" : percent(d.mean_kinship)}`,
  );
  return `${shown.join(" · ")} (${years.length === 1 ? "stängt år" : "stängda år"})`;
}

const swedishDate = (iso: string) =>
  new Date(iso).toLocaleDateString("sv-SE", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

const pctLabel = (val: number) => `${decimal(val, 1)}\u00a0%`;

interface OverviewTabProps {
  genebankId: number;
}

const FounderChart = ({
  theme,
  founders,
}: { theme: Theme } & {
  founders: [string, number][]; // [founder_id, contribution] tuples
}) => {
  const top10 = founders.slice(0, 10);
  const categories = top10.map((f) => f[0]); // founder_id
  const data = top10.map((f) => Math.round(f[1] * 1000) / 10); // contribution

  const options = {
    chart: { toolbar: { show: false }, foreColor: theme.palette.ink["3"] },
    grid: { borderColor: theme.palette.line.faint },
    plotOptions: {
      bar: { horizontal: true, borderRadius: 4 },
    },
    dataLabels: {
      enabled: true,
      formatter: pctLabel,
    },
    xaxis: {
      categories,
      labels: { formatter: (val: string) => pctLabel(Number(val)) },
    },
    colors: [theme.palette.skog.main],
    tooltip: {
      y: { formatter: pctLabel },
    },
  };

  const series = [{ name: "Andel av generna", data }];

  return (
    <Box sx={{ height: 350, width: "100%" }}>
      <Chart options={options} series={series} type="bar" height="350" />
    </Box>
  );
};

const ThemedFounderChart = withTheme(FounderChart);

const OverviewTab = ({ genebankId }: OverviewTabProps) => {
  const {
    data: metrics,
    isLoading: metricsLoading,
    error: metricsError,
    refetch: refetchMetrics,
  } = useFetchPopulationMetricsQuery(genebankId);

  const {
    data: founders,
    isLoading: foundersLoading,
    error: foundersError,
    refetch: refetchFounders,
  } = useFetchFounderStatisticsQuery(genebankId);

  // The founderdjur table's rows (the same request as the table below), so the
  // card and the table count the same animals. Until it arrives the count is left out.
  const { data: founderRows, error: founderError } =
    useFetchFoundersAtRiskQuery(genebankId);
  // The trend below shares this request; its last row is the last closed year.
  const { data: trend } = useFetchGeneticsTrendsQuery(genebankId);

  if (metricsLoading || foundersLoading) {
    return (
      <React.Fragment>
        <Alert severity="info" sx={{ mb: 6 }}>
          Beräknar genetiska nyckeltal — detta kan ta upp till en minut vid
          första anropet.
        </Alert>
        <Grid container spacing={6}>
          {[1, 2, 3, 4].map((i) => (
            <Grid key={i} size={{ xs: 12, sm: 6, md: 3 }}>
              <Skeleton variant="rounded" height={140} />
            </Grid>
          ))}
        </Grid>
      </React.Fragment>
    );
  }

  const error = metricsError ?? foundersError;
  if (error) {
    return (
      <GeneticsError
        error={error}
        onRetry={() => {
          refetchMetrics();
          refetchFounders();
        }}
      />
    );
  }

  if (!metrics || !founders) return null;

  // An empty genebank gets "–", never zeros that read as healthy (the API answers 0 there).
  const empty = metrics.n_active === 0;
  const ne = metrics.effective_population_size;
  const nWithCarriers = founderRows?.filter(
    (f) => f.risk_level !== "lost",
  ).length;

  return (
    <React.Fragment>
      <GeneticsInfoPanel tab="overview" />
      {empty && (
        <Alert severity="info" sx={{ mb: 6 }}>
          Det finns inga kaniner i beräkningen för den här genbanken, så
          nyckeltalen kan inte räknas. Vilka kaniner som räknas står under
          Förklaringar.
        </Alert>
      )}
      {/* While the founder table shows an error, "Se vilka" would have nothing to go to. */}
      <Laget
        metrics={metrics}
        founders={founderError ? undefined : founderRows}
      />
      <Grid
        container
        spacing={6}
        sx={{
          mb: 6,
        }}
      >
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Kaniner i beräkningen"
            value={decimal(metrics.n_active)}
            subtitle={
              metrics.reference_start
                ? `levande, med intyg, i en aktiv besättning, rapporterade sedan ${swedishDate(metrics.reference_start)}`
                : "levande, med intyg, i en aktiv besättning"
            }
            tooltip={IN_CALCULATION}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Effektiv populationsstorlek (Ne)"
            value={
              ne == null || empty
                ? "–"
                : metrics.ne_se != null
                  ? `${decimal(ne)} ± ${decimal(metrics.ne_se)}`
                  : decimal(ne)
            }
            subtitle="mål minst 50 (FAO), helst 100 (Frankham m.fl. 2014)"
            tooltip="Hur stor en idealisk population skulle vara för att förlora genetisk variation lika långsamt som genbanken. Räknat från hur mycket inaveln har ökat per generation hos varje kanin i beräkningen, sedan stamboken började (Gutiérrez m.fl. 2008). Talet efter ± är osäkerheten."
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Effektivt antal founderdjur (FE)"
            value={empty ? "–" : decimal(founders.founder_equivalents, 1)}
            subtitle={
              empty || nWithCarriers === undefined
                ? undefined
                : // FE also counts unknown parents, so the count is its basis, not its ceiling.
                  `räknat på ${nWithCarriers} founderdjur med bärare i beräkningen och på okända föräldrar`
            }
            tooltip={`${FOUNDERDJUR} FE är så många founderdjur som, om alla hade lämnat lika stor andel av generna, skulle ge samma spridning av generna som i dag (Lacy 1989). En okänd förälder till en kanin med bara en känd förälder räknas här som ett eget founderdjur, så FE kan bli större än antalet founderdjur med bärare.`}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Medelsläktskap (MK)"
            value={empty ? "–" : percent(metrics.mean_kinship)}
            subtitle={trend ? closedYearsMk(trend) : undefined}
            tooltip={`${MK_TEXT} Det stora talet gäller i dag. Åren under är räknade på varje års kaniner, så de är inte samma population som i dag: jämför åren med varandra, inte med dagens tal.`}
          />
        </Grid>
      </Grid>

      <Grid container spacing={6}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Card sx={{ mb: 6 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Founderdjur med störst andel av generna
              </Typography>
              {founders.top_founders && founders.top_founders.length > 0 ? (
                <ThemedFounderChart founders={founders.top_founders} />
              ) : (
                <Typography variant="body2" color="textSecondary">
                  Inga founderdjur att visa.
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Card sx={{ mb: 6 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Inavel
              </Typography>
              <List dense>
                <ListItem>
                  <ListItemText
                    primary="Genomsnittlig inavel (F)"
                    secondary={empty ? "–" : percent(metrics.mean_inbreeding)}
                  />
                </ListItem>
                <ListItem>
                  <ListItemText
                    primary="Inavelsökning per generation (ΔF)"
                    secondary={
                      metrics.delta_f == null || empty
                        ? "–"
                        : `${percent(metrics.delta_f, 2)} · mål under 1\u00a0% (FAO)`
                    }
                  />
                </ListItem>
              </List>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <TrendChart genebankId={genebankId} />

      <FoundersAtRiskPanel genebankId={genebankId} />
    </React.Fragment>
  );
};

export default OverviewTab;
