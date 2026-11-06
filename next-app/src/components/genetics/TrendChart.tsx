import React, { useMemo, useState } from "react";
import {
  Card,
  CardContent,
  Typography,
  Skeleton,
  Alert,
  ToggleButton,
  ToggleButtonGroup,
  Box,
  IconButton,
} from "@mui/material";
import { ChevronLeft, ChevronRight, ZoomOut } from "@mui/icons-material";
import dynamic from "next/dynamic";
import { useTheme } from "@mui/material/styles";

import {
  useFetchGeneticsTrendsQuery,
  TrendDataPoint,
} from "@/redux/api/apiSlice";

const Chart = dynamic(() => import("react-apexcharts"), {
  ssr: false,
});

const DEFAULT_WINDOW = 5;

interface TrendChartProps {
  genebankId: number;
}

const TrendChart = ({ genebankId }: TrendChartProps) => {
  const { data, isLoading, error } = useFetchGeneticsTrendsQuery(genebankId);
  const theme = useTheme();

  const [visibleSeries, setVisibleSeries] = useState<string[]>(["ne", "fe"]);
  const [windowEnd, setWindowEnd] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);

  const years = useMemo(() => data?.map((d) => d.year) ?? [], [data]);
  const maxYear = years.length > 0 ? Math.max(...years) : 0;
  const minYear = years.length > 0 ? Math.min(...years) : 0;

  const effectiveEnd = windowEnd ?? maxYear;
  const effectiveStart = showAll
    ? minYear
    : Math.max(minYear, effectiveEnd - DEFAULT_WINDOW + 1);

  const windowData = useMemo(
    () =>
      data?.filter((d) => d.year >= effectiveStart && d.year <= effectiveEnd) ??
      [],
    [data, effectiveStart, effectiveEnd],
  );

  if (isLoading) {
    return <Skeleton variant="rounded" height={300} sx={{ mb: 6 }} />;
  }

  const isAuthError =
    error != null &&
    typeof error === "object" &&
    "status" in error &&
    (error as { status: unknown }).status === 401;

  if (error && !isAuthError) {
    return (
      <Alert severity="error" sx={{ mb: 6 }}>
        Kunde inte hämta trenddata.
      </Alert>
    );
  }

  if (!data || data.length < 2) return null;

  const seriesConfig: Record<
    string,
    { name: string; key: keyof TrendDataPoint; yAxis: number; color: string }
  > = {
    ne: {
      name: "Ne",
      key: "effective_population_size",
      yAxis: 0,
      color: theme.palette.skog.main,
    },
    fe: {
      name: "FE",
      key: "founder_equivalents",
      yAxis: 0,
      color: theme.palette.mossa.main,
    },
    mk: {
      name: "Medel-MK",
      key: "mean_kinship",
      yAxis: 1,
      color: theme.palette.himmel.main,
    },
    f: {
      name: "Medel-F",
      key: "mean_inbreeding",
      yAxis: 1,
      color: theme.palette.lera.main,
    },
  };

  const series = visibleSeries
    .filter((key) => key in seriesConfig)
    .map((key) => {
      const cfg = seriesConfig[key];
      return {
        name: cfg.name,
        data: windowData.map((d) => {
          const val = d[cfg.key];
          return val !== null && val !== undefined
            ? Math.round((val as number) * 1000) / 1000
            : null;
        }),
      };
    });

  const categories = windowData.map((d) => d.year.toString());

  const hasLowQuality = windowData.some((d) => d.data_quality === "low");

  // Each metric gets its own independent y-axis so different scales
  // (Ne ~380, FGE ~20, MK ~0.04) are all clearly visible.
  // ApexCharts needs one yaxis entry per series.
  const activeKeys = visibleSeries.filter((key) => key in seriesConfig);
  const activeConfigs = activeKeys.map((key) => seriesConfig[key]);

  let leftSeen = 0;
  let rightSeen = 0;

  const yaxis = activeConfigs.map((cfg) => {
    const isRight = cfg.yAxis === 1;
    if (isRight) {
      rightSeen++;
      return {
        seriesName: cfg.name,
        opposite: true,
        title: { text: rightSeen === 1 ? cfg.name : "" },
        show: rightSeen === 1,
        min: 0,
        forceNiceScale: true,
      };
    }
    leftSeen++;
    return {
      seriesName: cfg.name,
      opposite: false,
      title: { text: leftSeen === 1 ? cfg.name : "" },
      show: leftSeen === 1,
      forceNiceScale: true,
    };
  });

  // Key forces ApexCharts to fully re-mount when series or window changes,
  // preventing corrupt axis state from dynamic updates.
  const chartKey = `${activeKeys.join(",")}_${effectiveStart}_${effectiveEnd}`;

  const options: ApexCharts.ApexOptions = {
    chart: {
      type: "line",
      toolbar: { show: false },
      background: "transparent",
      fontFamily: theme.typography.fontFamily,
      foreColor: theme.palette.ink["3"],
    },
    grid: { borderColor: theme.palette.line.faint },
    theme: { mode: theme.palette.mode },
    stroke: {
      width: 2,
      curve: "smooth",
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
    yaxis: yaxis.length > 0 ? yaxis : [{ show: true }],
    colors: activeKeys.map((key) => seriesConfig[key].color),
    tooltip: {
      shared: true,
      y: {
        formatter: (val: number) => (val !== null ? val.toFixed(3) : "–"),
      },
    },
    annotations: hasLowQuality
      ? {
          xaxis: [
            {
              x: categories[0],
              x2: categories.find(
                (_, i) => windowData[i]?.data_quality !== "low",
              ),
              fillColor: theme.palette.paper["2"],
              label: {
                text: "Lägre datakvalitet",
                style: { fontSize: "10px" },
              },
            },
          ],
        }
      : undefined,
    legend: { show: false },
  };

  const canStepBack = effectiveStart > minYear && !showAll;
  const canStepForward = effectiveEnd < maxYear && !showAll;

  return (
    <Card sx={{ mb: 6 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Genetiska trender
        </Typography>

        <Box
          sx={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            mb: 2,
          }}
        >
          <ToggleButtonGroup
            size="small"
            value={visibleSeries}
            onChange={(_, newVal) => {
              if (newVal.length > 0) setVisibleSeries(newVal);
            }}
          >
            {Object.entries(seriesConfig).map(([key, cfg]) => (
              <ToggleButton key={key} value={key}>
                <Box
                  component="span"
                  sx={{
                    width: 12,
                    height: 3,
                    bgcolor: cfg.color,
                    borderRadius: 1,
                    mr: 0.75,
                    display: "inline-block",
                  }}
                />
                {cfg.name}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>

          <Box>
            <IconButton
              size="small"
              disabled={!canStepBack}
              onClick={() =>
                setWindowEnd((prev) =>
                  Math.max(
                    minYear + DEFAULT_WINDOW - 1,
                    (prev ?? maxYear) - DEFAULT_WINDOW,
                  ),
                )
              }
            >
              <ChevronLeft />
            </IconButton>
            <IconButton
              size="small"
              onClick={() => {
                setShowAll(!showAll);
                setWindowEnd(null);
              }}
              color={showAll ? "primary" : "default"}
              title={showAll ? "Visa 5 år" : "Visa alla år"}
            >
              <ZoomOut />
            </IconButton>
            <IconButton
              size="small"
              disabled={!canStepForward}
              onClick={() =>
                setWindowEnd((prev) =>
                  Math.min(maxYear, (prev ?? maxYear) + DEFAULT_WINDOW),
                )
              }
            >
              <ChevronRight />
            </IconButton>
          </Box>
        </Box>

        <Chart
          key={chartKey}
          options={options}
          series={series}
          type="line"
          height={300}
        />

        {hasLowQuality && (
          <Typography
            variant="caption"
            color="textSecondary"
            sx={{ mt: 1, display: "block" }}
          >
            Datapunkter före 2005 baseras på uppskattningar (death_note-år + max
            ålder) och har lägre tillförlitlighet.
          </Typography>
        )}
      </CardContent>
    </Card>
  );
};

export default TrendChart;
