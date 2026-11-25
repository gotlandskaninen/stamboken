import React from "react";

import { Card, CardContent, Typography } from "@mui/material";
import HelpTooltip from "./HelpTooltip";

interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  tooltip?: string;
}

const KpiCard = ({ title, value, subtitle, tooltip }: KpiCardProps) => {
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
            {subtitle}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
};

export default KpiCard;
