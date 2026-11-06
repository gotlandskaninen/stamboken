interface IconProps {
  d: string | readonly string[];
  size?: number;
  stroke?: number;
}

export function Icon({ d, size = 18, stroke = 1.6 }: IconProps) {
  const paths = Array.isArray(d) ? d : [d];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flex: "0 0 auto" }}
    >
      {paths.map((p, i) => (
        <path key={i} d={p} />
      ))}
    </svg>
  );
}

export const ICONS = {
  arrow: "M5 12h14m-5-6 6 6-6 6",
  heart: "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z",
  book: ["M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2V5Z", "M8 7h8M8 11h8M8 15h5"],
  message: ["M4 5h16v11H8l-4 4V5Z"],
  shield: ["M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z", "m9 12 2 2 4-4"],
  leaf: ["M5 19c0-8 6-14 14-14 0 8-6 14-14 14Z", "M5 19c4-4 6-6 14-14"],
  check: "m5 12 4 4 10-10",
  mail: ["M3 6h18v12H3z", "m3 7 9 7 9-7"],
  pedigree: [
    "M12 4v3",
    "M6 11V8h12v3",
    "M3 17v-3h6v3M15 17v-3h6v3",
    "M6 14v-3M18 14v-3",
  ],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M4 21a8 8 0 0 1 16 0"],
} as const;
