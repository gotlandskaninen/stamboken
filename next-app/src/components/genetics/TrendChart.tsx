import React, { useState } from "react";
import {
  Card,
  CardContent,
  Typography,
  Skeleton,
  ToggleButton,
  ToggleButtonGroup,
  Box,
} from "@mui/material";
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
    markers: { size: 4 },
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
        formatter: (v: number | null) => (v == null ? "–" : metric.format(v)),
      },
    },
    annotations: hasLowQuality
      ? {
          xaxis: [
            {
              x: categories[0],
              x2: String(firstReliableYear),
              fillColor: theme.palette.paper["2"],
              label: {
                text: "Osäkrare värden",
                style: { fontSize: "10px" },
              },
            },
          ],
        }
      : undefined,
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

        {values.some((v) => v != null) ? (
          <Chart
            key={metricKey}
            options={options}
            series={[{ name: metric.name, data: values }]}
            type="line"
            height={300}
          />
        ) : (
          <Typography variant="body2" color="textSecondary">
            {metric.name} kan inte räknas för de här åren.
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
      </CardContent>
    </Card>
  );
};

export default TrendChart;
