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
      {/* Keyboard focus opens it; on a touch screen a tap does. */}
      <Tooltip
        title={tooltip}
        arrow
        placement="top"
        describeChild
        enterTouchDelay={0}
        leaveTouchDelay={8000}
      >
        <IconButton size="small" aria-label="Förklaring" sx={{ p: 0, ml: 0.5 }}>
          <HelpOutlineIcon sx={{ fontSize: 16, opacity: 0.6 }} />
        </IconButton>
      </Tooltip>
    </span>
  );
};

export default HelpTooltip;
