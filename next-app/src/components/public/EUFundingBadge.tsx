import { Box } from "@mui/material";

const SRC = {
  vertical: "/static/img/stamboken/eu/medfinansieras-av-eu.svg",
  horizontal: "/static/img/stamboken/eu/medfinansieras-av-eu-horizontal.svg",
} as const;

/**
 * Official EU funding lockup — emblem + "Medfinansieras av Europeiska unionen".
 *
 * Renders the unmodified official Commission artwork (the EPS converted to SVG,
 * text outlined to paths) on a white card. The white card is required: the
 * positive/blue lockup must sit on a white background per Jordbruksverket's
 * rules, and it keeps the blue text legible over the dark sections too.
 * https://jordbruksverket.se/stod/eus-politik-for-jordbruk-och-fiske/pengar-fran-eu---anvand-eu-logotyp
 */
export function EUFundingBadge({
  orientation = "vertical",
  height,
}: {
  orientation?: "vertical" | "horizontal";
  height?: number;
}) {
  const h = height ?? (orientation === "vertical" ? 100 : 52);
  return (
    <Box
      sx={{
        display: "inline-flex",
        bgcolor: "#FFFFFF",
        p: 1.25,
        borderRadius: "4px",
        border: "1px solid rgba(31,27,22,0.10)",
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={SRC[orientation]}
        alt="Medfinansieras av Europeiska unionen"
        height={h}
        style={{ display: "block", height: h, width: "auto" }}
      />
    </Box>
  );
}
