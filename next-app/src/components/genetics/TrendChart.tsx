import React, { useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Card,
  CardContent,
  Typography,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Box,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import dynamic from "next/dynamic";
import { useTheme } from "@mui/material/styles";

import {
  useFetchGeneticsTrendsQuery,
  TrendDataPoint,
} from "@/redux/api/apiSlice";
import { decimal, percent } from "@/lib/genetics";
import GeneticsError from "./GeneticsError";

const Chart = dynamic(() => import("react-apexcharts"), {
  ssr: false,
});

type MetricKey = "ne" | "fe" | "mk" | "f";

// Fewer rabbits than this behind a year's Ne give a shaky estimate (rp.MIN_HISTORY_MEMBERS).
const RELIABLE_NE_N = 30;

const neWithUncertainty = (d: TrendDataPoint) =>
  `${decimal(d.effective_population_size as number)}` +
  (d.ne_se != null ? ` ± ${decimal(d.ne_se)}` : "") +
  (d.ne_n != null ? `, ${decimal(d.ne_n)} kaniner` : "");

// One metric at a time: two units never share a plot.
const metrics: Record<
  MetricKey,
  { name: string; key: keyof TrendDataPoint; format: (v: number) => string }
> = {
  ne: {
    name: "Ne",
    key: "effective_population_size",
    format: (v) => decimal(v),
  },
  fe: { name: "FE", key: "founder_equivalents", format: (v) => decimal(v, 1) },
  mk: {
    name: "Medelsläktskap (MK)",
    key: "mean_kinship",
    format: (v) => percent(v),
  },
  f: { name: "Inavel (F)", key: "mean_inbreeding", format: (v) => percent(v) },
};

interface TrendChartProps {
  genebankId: number;
}

const TrendChart = ({ genebankId }: TrendChartProps) => {
  const { data, isLoading, error, refetch } =
    useFetchGeneticsTrendsQuery(genebankId);
  const theme = useTheme();

  const [metricKey, setMetricKey] = useState<MetricKey>("ne");

  if (isLoading) {
    return <Skeleton variant="rounded" height={300} sx={{ mb: 6 }} />;
  }

  if (error) {
    return <GeneticsError error={error} onRetry={refetch} />;
  }

  if (!data || data.length < 2) return null;

  const metric = metrics[metricKey];
  const values = data.map((d) => d[metric.key] as number | null);
  const known = values.filter((v) => v != null).length;
  // Ne only: years estimated from few rabbits get a hollow marker.
  const shaky =
    metricKey === "ne"
      ? data.flatMap((d, i) =>
          d.effective_population_size != null &&
          d.ne_n != null &&
          d.ne_n < RELIABLE_NE_N
            ? [i]
            : [],
        )
      : [];
  const categories = data.map((d) => d.year.toString());
  const firstReliableYear = data.find((d) => d.data_quality !== "low")?.year;
  const hasLowQuality =
    firstReliableYear !== undefined && data[0].data_quality === "low";

  const options: ApexCharts.ApexOptions = {
    chart: {
      type: "line",
      toolbar: { show: false },
      zoom: { enabled: false },
      background: "transparent",
      fontFamily: theme.typography.fontFamily,
      foreColor: theme.palette.ink["3"],
    },
    grid: { borderColor: theme.palette.line.faint },
    theme: { mode: theme.palette.mode },
    stroke: { width: 2, curve: "straight" },
    markers: {
      size: 4,
      discrete: shaky.map((i) => ({
        seriesIndex: 0,
        dataPointIndex: i,
        size: 4,
        fillColor: theme.palette.background.paper,
        strokeColor: theme.palette.skog.main,
      })),
    },
    xaxis: {
      categories,
      title: { text: "År" },
      labels: {
        rotate: -45,
        rotateAlways: categories.length > 10,
        style: { fontSize: "11px" },
      },
      tickAmount: Math.min(categories.length, 15),
    },
    yaxis: {
      min: 0,
      forceNiceScale: true,
      title: { text: metric.name },
      labels: { formatter: (v: number) => metric.format(v) },
    },
    colors: [theme.palette.skog.main],
    tooltip: {
      y: {
        formatter: (v: number | null, opts?: { dataPointIndex: number }) =>
          v == null
            ? "–"
            : metricKey === "ne" && opts
              ? neWithUncertainty(data[opts.dataPointIndex])
              : metric.format(v),
      },
    },
    // Always an object: an update with annotations undefined makes ApexCharts throw
    // (it reads annotations.images) and drop the axes.
    annotations: {
      xaxis: hasLowQuality
        ? [
            {
              x: categories[0],
              x2: String(firstReliableYear),
              fillColor: theme.palette.paper["2"],
              label: {
                text: "Osäkrare värden",
                style: { fontSize: "10px" },
              },
            },
          ]
        : [],
    },
    legend: { show: false },
  };

  return (
    <Card sx={{ mb: 6 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Genetiska trender
        </Typography>
        <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
          Ett värde per stängd årsrapportering, räknat på kaninerna det året.
          Korten ovan visar läget i dag.
        </Typography>

        <Box sx={{ mb: 2 }}>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={metricKey}
            aria-label="Mått i diagrammet"
            onChange={(_, next: MetricKey | null) => {
              if (next) setMetricKey(next);
            }}
          >
            {(Object.keys(metrics) as MetricKey[]).map((key) => (
              <ToggleButton key={key} value={key}>
                {metrics[key].name}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>

        {known > 0 ? (
          <Chart
            key={metricKey}
            options={options}
            series={[{ name: metric.name, data: values }]}
            type="line"
            height={300}
          />
        ) : (
          <Typography variant="body2" color="textSecondary">
            {metricKey !== "ne"
              ? `Inga värden för ${metric.name} de här åren.`
              : // ne_n is null only on rows stored before Ne was: they are not recomputed yet.
                data.every((d) => d.ne_n == null)
                ? "Inga värden för Ne de här åren ännu. Efter en uppdatering räknas de fram i bakgrunden, så ladda om sidan om en stund."
                : "Ne kan inte skattas för de här åren: för få kaniner med känd stamtavla i de här åren."}
          </Typography>
        )}

        {shaky.length > 0 && (
          <Typography
            variant="caption"
            color="textSecondary"
            sx={{ mt: 1, display: "block" }}
          >
            Ihålig punkt: osäker skattning, färre än {RELIABLE_NE_N} kaniner.
          </Typography>
        )}

        {metricKey === "ne" && known > 0 && known < values.length && (
          <Typography
            variant="caption"
            color="textSecondary"
            sx={{ mt: 1, display: "block" }}
          >
            Ne saknas för år där ingen kanin har mer än en generation känd
            bakåt, eller där inaveln inte ökade.
          </Typography>
        )}

        {hasLowQuality && (
          <Typography
            variant="caption"
            color="textSecondary"
            sx={{ mt: 1, display: "block" }}
          >
            Värden före {firstReliableYear} är osäkrare: när dödsdatum saknas
            uppskattas det från dödsorsaken eller kaninens högsta ålder.
          </Typography>
        )}

        {/* The same values for keyboard and screen readers; the chart's tooltip needs a mouse. */}
        <Accordion
          disableGutters
          sx={{ mt: 2, "&::before": { display: "none" } }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2">Visa som tabell</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>År</TableCell>
                  <TableCell align="right">{metric.name}</TableCell>
                  {metricKey === "ne" && (
                    <>
                      <TableCell align="right">Osäkerhet (±)</TableCell>
                      <TableCell align="right">Antal kaniner</TableCell>
                    </>
                  )}
                </TableRow>
              </TableHead>
              <TableBody>
                {data.map((d, i) => (
                  <TableRow key={d.year}>
                    <TableCell>{d.year}</TableCell>
                    <TableCell align="right">
                      {values[i] == null ? "–" : metric.format(values[i])}
                    </TableCell>
                    {metricKey === "ne" && (
                      <>
                        <TableCell align="right">
                          {d.ne_se == null ? "–" : decimal(d.ne_se)}
                        </TableCell>
                        <TableCell align="right">
                          {d.ne_n == null ? "–" : decimal(d.ne_n)}
                        </TableCell>
                      </>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </AccordionDetails>
        </Accordion>
      </CardContent>
    </Card>
  );
};

export default TrendChart;
