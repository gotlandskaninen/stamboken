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
} from "@/redux/api/apiSlice";
import KpiCard, { ThresholdLevel } from "./KpiCard";
import GeneticsInfoPanel from "./GeneticsInfoPanel";
import HelpTooltip from "./HelpTooltip";
import TrendChart from "./TrendChart";
import FoundersAtRiskPanel from "./FoundersAtRiskPanel";
import type { Theme } from "@mui/material/styles";

const Chart = dynamic(() => import("react-apexcharts"), {
  ssr: false,
});

function getMkLevel(mk: number): ThresholdLevel {
  if (mk < 0.05) return "good";
  if (mk <= 0.1) return "warning";
  return "danger";
}

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
      formatter: (val: number) => `${val}%`,
    },
    xaxis: {
      categories,
      labels: { formatter: (val: string) => `${val}%` },
    },
    colors: [theme.palette.skog.main],
    tooltip: {
      y: { formatter: (val: number) => `${val}%` },
    },
  };

  const series = [{ name: "Bidrag", data }];

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
  } = useFetchPopulationMetricsQuery(genebankId);

  const {
    data: founders,
    isLoading: foundersLoading,
    error: foundersError,
  } = useFetchFounderStatisticsQuery(genebankId);

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

  const isAuthError = (err: unknown) =>
    err != null &&
    typeof err === "object" &&
    "status" in err &&
    (err as { status: unknown }).status === 401;

  if (
    (metricsError && !isAuthError(metricsError)) ||
    (foundersError && !isAuthError(foundersError))
  ) {
    return (
      <Alert severity="error">
        Kunde inte hämta genetikdata. Kontrollera att du har behörighet.
      </Alert>
    );
  }

  if (!metrics || !founders) return null;

  return (
    <React.Fragment>
      <GeneticsInfoPanel tab="overview" />
      <Grid
        container
        spacing={6}
        sx={{
          mb: 6,
        }}
      >
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Aktiva individer"
            value={String(metrics.n_active)}
            subtitle="i genbanken"
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Effektiv pop.storlek (Ne)"
            value={
              metrics.effective_population_size == null
                ? "–"
                : metrics.ne_se != null
                  ? `${metrics.effective_population_size.toFixed(0)} ± ${metrics.ne_se.toFixed(0)}`
                  : metrics.effective_population_size.toFixed(0)
            }
            subtitle="Realiserat sedan grundandet"
            tooltip="Effektiv populationsstorlek skattad från varje djurs inavelsökning per generation (Gutiérrez m.fl. 2008), över referenspopulationen. Beskriver takten sedan stamboken började, inte bara i dag. Riktmärken: FAO anger minst 50 på kort sikt; Frankham m.fl. 2014 minst 100."
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Founder-ekvivalenter (FE)"
            value={founders.founder_equivalents.toFixed(1)}
            subtitle={`av ${founders.n_founders} founders`}
            tooltip="Founder-ekvivalenter — antal founders som skulle ge samma genetiska diversitet om de bidrog lika (Lacy 1989). Högt = jämnare fördelning."
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <KpiCard
            title="Genomsnittlig MK"
            value={metrics.mean_kinship.toFixed(4)}
            subtitle={metrics.mean_kinship < 0.05 ? "Låg nivå" : "Förhöjd nivå"}
            level={getMkLevel(metrics.mean_kinship)}
            tooltip="Genomsnittlig medelkinship — medelvärde av parvisa kinship-koefficienter. Lågt = mer genetisk diversitet."
          />
        </Grid>
      </Grid>

      <Grid container spacing={6}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Card sx={{ mb: 6 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Founder-bidrag (topp 10)
              </Typography>
              {founders.top_founders && founders.top_founders.length > 0 ? (
                <ThemedFounderChart founders={founders.top_founders} />
              ) : (
                <Typography variant="body2" color="textSecondary">
                  Ingen founder-data tillgänglig.
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Card sx={{ mb: 6 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Populationssammanfattning
              </Typography>
              <List dense>
                <ListItem>
                  <ListItemText
                    primary="Antal founders"
                    secondary={founders.n_founders}
                  />
                </ListItem>
                <ListItem>
                  <ListItemText
                    primary="Founder-ekvivalenter (FE)"
                    secondary={founders.founder_equivalents.toFixed(1)}
                  />
                </ListItem>
                <ListItem>
                  <ListItemText
                    primary={
                      <HelpTooltip tooltip="Andel av grundarnas genetiska variation som gått förlorad (= medelsläktskap i referenspopulationen).">
                        Diversitetsförlust
                      </HelpTooltip>
                    }
                    secondary={`${(founders.proportional_loss * 100).toFixed(1)}%`}
                  />
                </ListItem>
                <ListItem>
                  <ListItemText
                    primary="Medelinavel (F)"
                    secondary={metrics.mean_inbreeding.toFixed(4)}
                  />
                </ListItem>
                <ListItem>
                  <ListItemText
                    primary="Inavelsökningstakt (ΔF)"
                    secondary={
                      metrics.delta_f == null ? "–" : metrics.delta_f.toFixed(5)
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
