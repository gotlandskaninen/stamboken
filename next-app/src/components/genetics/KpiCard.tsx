import React from "react";

import { Box, Card, CardContent, Typography } from "@mui/material";
import HelpTooltip from "./HelpTooltip";

export type ThresholdLevel = "good" | "warning" | "danger" | "neutral";

// Neutral has no dot: a grey dot says nothing.
const levelColors: Record<ThresholdLevel, string | undefined> = {
  good: "var(--sb-success)",
  warning: "var(--sb-warning)",
  danger: "var(--sb-danger)",
  neutral: undefined,
};

interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  level?: ThresholdLevel;
  tooltip?: string;
}

const KpiCard = ({
  title,
  value,
  subtitle,
  level = "neutral",
  tooltip,
}: KpiCardProps) => {
  const color = levelColors[level];

  return (
    <Card sx={{ height: "100%" }}>
      <CardContent sx={{ "&:last-child": { pb: 4 } }}>
        <Typography variant="h6" sx={{ mb: 4 }}>
          {tooltip ? (
            <HelpTooltip tooltip={tooltip}>{title}</HelpTooltip>
          ) : (
            title
          )}
        </Typography>
        <Typography
          variant="h3"
          component="p"
          sx={{
            mb: 3,
            color: "var(--sb-skog)",
            fontWeight: "fontWeightRegular",
          }}
        >
          {value}
        </Typography>
        {subtitle && (
          <Typography variant="subtitle2" component="p" color="textSecondary">
            {color && (
              <Box
                component="span"
                sx={{
                  display: "inline-block",
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  bgcolor: color,
                  mr: 1,
                }}
              />
            )}
            {subtitle}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
};

export default KpiCard;
