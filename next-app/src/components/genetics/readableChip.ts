// The theme's warning and info chips reach 2.7:1 and 4.3:1 on their soft fills;
// ink-2 and info reach 9.4:1 and 4.6:1. Same selector as the theme, so this wins.
export const readableChip = {
  "&.MuiChip-colorWarning": { color: "var(--sb-ink-2)" },
  "&.MuiChip-colorInfo": { color: "var(--sb-info)" },
};
