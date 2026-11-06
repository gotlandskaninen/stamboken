import React from "react";
import { Tooltip, IconButton } from "@mui/material";
import HelpOutlineIcon from "@mui/icons-material/HelpOutlined";

interface HelpTooltipProps {
  tooltip: string;
  children: React.ReactNode;
}

const HelpTooltip = ({ tooltip, children }: HelpTooltipProps) => {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {children}
      <Tooltip title={tooltip} arrow placement="top">
        <IconButton size="small" tabIndex={-1} sx={{ p: 0, ml: 0.5 }}>
          <HelpOutlineIcon sx={{ fontSize: 16, opacity: 0.6 }} />
        </IconButton>
      </Tooltip>
    </span>
  );
};

export default HelpTooltip;
