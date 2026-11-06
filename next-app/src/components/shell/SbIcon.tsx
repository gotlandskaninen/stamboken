import type { CSSProperties } from "react";

// Stroked line icons (24×24, stroke 1.6, round caps) — recreated from the
// design handoff (components.jsx `Icons` + min-besattning-page.jsx `MbIcons`).
const PATHS = {
  // Tre punkter som små strokade cirklar — h.01-prickar blir för svaga
  // under 20px.
  more: [
    "M4.5 12a.75.75 0 1 0 1.5 0 .75.75 0 1 0-1.5 0",
    "M11.25 12a.75.75 0 1 0 1.5 0 .75.75 0 1 0-1.5 0",
    "M18 12a.75.75 0 1 0 1.5 0 .75.75 0 1 0-1.5 0",
  ],
  search: ["M11 19a8 8 0 1 1 5.3-2L21 21"],
  menu: ["M3 6h18", "M3 12h18", "M3 18h18"],
  arrow: ["M5 12h14m-5-6 6 6-6 6"],
  arrowSm: ["M4 10h12m-4-4 4 4-4 4"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M4 21a8 8 0 0 1 16 0"],
  rabbit: [
    "M8 13c-2 0-3 1.5-3 3.5S6 20 8.5 20H16c2 0 3-1.5 3-3.5 0-3-3-4.5-5-4.5",
    "M10 11c-1-1-2-3-2-5 0-1.5 1-2 1.6-1 .8 1.5 1.4 3 1.4 4",
    "M14 11c1-1 2-3 2-5 0-1.5-1-2-1.6-1-.8 1.5-1.4 3-1.4 4",
    "M12 17h.01",
  ],
  leaf: ["M5 19c0-8 6-14 14-14 0 8-6 14-14 14Z", "M5 19c4-4 6-6 14-14"],
  chart: ["M4 20V4", "M4 20h16", "M8 16V10", "M12 16V6", "M16 16v-3"],
  shield: ["M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z", "m9 12 2 2 4-4"],
  book: ["M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2V5Z", "M8 7h8M8 11h8M8 15h5"],
  pin: [
    "M12 21s7-7 7-12a7 7 0 1 0-14 0c0 5 7 12 7 12Z",
    "M12 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
  ],
  mail: ["M3 6h18v12H3z", "m3 7 9 7 9-7"],
  globe: [
    "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
    "M3 12h18",
    "M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  ],
  calendar: ["M4 6h16v15H4z", "M4 10h16", "M9 3v4M15 3v4"],
  heart: [
    "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z",
  ],
  message: ["M4 5h16v11H8l-4 4V5Z"],
  plus: ["M12 5v14", "M5 12h14"],
  camera: [
    "M5 7h3l2-2h4l2 2h3v12H5z",
    "M12 16a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
  ],
  check: ["m5 12 4 4 10-10"],
  warn: ["M12 4 3 20h18L12 4Z", "M12 10v4", "M12 17h.01"],
  cross: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", "m9 9 6 6m0-6-6 6"],
  star: ["m12 4 2.4 5 5.6.8-4 4 1 5.6L12 16.8 7 19.4l1-5.6-4-4 5.6-.8L12 4Z"],
  download: ["M12 4v12", "m6 12 6 6 6-6", "M5 21h14"],
  pedigree: [
    "M12 4v3",
    "M6 11V8h12v3",
    "M3 17v-3h6v3M15 17v-3h6v3",
    "M6 14v-3M18 14v-3",
  ],
  egg: ["M12 3c4 0 7 5 7 10s-3 8-7 8-7-3-7-8 3-10 7-10Z"],
  bell: ["M6 16v-5a6 6 0 0 1 12 0v5l2 2H4l2-2Z", "M10 21a2 2 0 0 0 4 0"],
  home: ["M4 11 12 4l8 7v9h-5v-6h-6v6H4v-9Z"],
  grid: ["M4 4h7v7H4z", "M13 4h7v7h-7z", "M4 13h7v7H4z", "M13 13h7v7h-7z"],
  dna: [
    "M7 3c0 6 10 6 10 12M17 3c0 6-10 6-10 12",
    "M7 15c0 3 2 6 5 6M17 15c0 3-2 6-5 6",
    "M8 7h8M8 17h8",
  ],
  logout: ["M15 4h5v16h-5", "M4 12h11", "m11 8 4 4-4 4"],
  // Adminpanel-chrome (fliknav, landing-kort) — kopierade verbatim
  // från stamboken-drift:docs/design/design_handoff_admin/surfaces/admin-page.jsx:5-6 (AdIcons.users/cog).
  users: [
    "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
    "M2.5 20a6.5 6.5 0 0 1 13 0",
    "M16 4.5a3.5 3.5 0 0 1 0 6.6",
    "M17.5 13.6a6.5 6.5 0 0 1 4 6.4",
  ],
  cog: [
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
    "M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1",
  ],
} as const;

export type SbIconName = keyof typeof PATHS;

export function SbIcon({
  name,
  size = 24,
  style,
}: {
  name: SbIconName;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ flex: "0 0 auto", ...style }}
    >
      {PATHS[name].map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}
