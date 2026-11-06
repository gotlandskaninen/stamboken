import React from "react";

import { Box, Card, CardContent, Typography } from "@mui/material";
import HelpTooltip from "./HelpTooltip";

export type ThresholdLevel = "good" | "warning" | "danger" | "neutral";

const levelColors: Record<ThresholdLevel, string> = {
  good: "#4F7A3F",
  warning: "#B98019",
  danger: "#A23A2A",
  neutral: "#9D978A",
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
        <Typography variant="h3" sx={{ mb: 3, color: "#2F4A32" }}>
          <Box
            sx={{
              fontWeight: "fontWeightRegular",
            }}
          >
            {value}
          </Box>
        </Typography>
        {subtitle && (
          <Typography variant="subtitle2" color="textSecondary">
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
            {subtitle}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
};

export default KpiCard;
