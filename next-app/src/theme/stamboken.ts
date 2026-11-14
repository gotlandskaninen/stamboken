import type {} from "@mui/x-data-grid/themeAugmentation";
import { createTheme, type Theme } from "@mui/material/styles";
import { svSE, enUS, deDE } from "@mui/material/locale";
import {
  svSE as dgSvSE,
  enUS as dgEnUS,
  deDE as dgDeDE,
} from "@mui/x-data-grid/locales";
import {
  svSE as dpSvSE,
  enUS as dpEnUS,
  deDE as dpDeDE,
} from "@mui/x-date-pickers/locales";

const displayFont = "'Source Serif 4', 'Iowan Old Style', Georgia, serif";
const bodyFont =
  "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const monoFont = "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace";

export const stambokenTheme = createTheme({
  spacing: 4,
  palette: {
    mode: "light",
    primary: { main: "#2F4A32", dark: "#1F3322", light: "#D7DFCF" },
    secondary: { main: "#6B8E54", light: "#E2E8D5" },
    error: { main: "#A23A2A", light: "#F0D4CC" },
    warning: { main: "#B98019", light: "#F2E4C2" },
    success: { main: "#4F7A3F", light: "#DDE6D2" },
    info: { main: "#3E6878", light: "#D5E1E6" },
    background: { default: "#F4F1EA", paper: "#FBF9F3" },
    text: { primary: "#1F1B16", secondary: "#3D362C" },
    divider: "#D7CFBE",
    skog: { main: "#2F4A32", deep: "#1F3322", soft: "#D7DFCF" },
    mossa: { main: "#6B8E54", soft: "#E2E8D5" },
    lera: { main: "#B85C38", soft: "#F3DDD0" },
    himmel: { main: "#4A6B7A", soft: "#D8E1E5" },
    paper: { main: "#F4F1EA", "2": "#EBE6D8", "3": "#E2DCC9" },
    card: "#FBF9F3",
    ink: { main: "#1F1B16", "2": "#3D362C", "3": "#6F6A5F", "4": "#9D978A" },
    line: { main: "#D7CFBE", strong: "#B8AE99", faint: "#E5DECB" },
    // .ad-table th background --sb-paper-2 (Adminpanel.html:53). x-data-grid v9
    // dropped `--DataGrid-containerBackground`; the header band is painted from
    // `palette.DataGrid.headerBg` (typed by the themeAugmentation import above).
    DataGrid: { headerBg: "#EBE6D8" },
  },
  shape: { borderRadius: 4 },
  shadows: [
    "none",
    "0 1px 0 rgba(31,27,22,0.06), 0 1px 2px rgba(31,27,22,0.04)",
    "0 2px 4px rgba(31,27,22,0.05), 0 6px 14px rgba(31,27,22,0.06)",
    "0 10px 28px rgba(31,27,22,0.10), 0 2px 6px rgba(31,27,22,0.05)",
    ...Array(21).fill("none"),
  ] as any,
  typography: {
    fontFamily: bodyFont,
    fontSize: 16,

    h1: {
      fontFamily: displayFont,
      textWrap: "balance",
      fontSize: "72px",
      lineHeight: 1.04,
      letterSpacing: "-0.02em",
      fontWeight: 400,
    },
    // h2–h4 are fluid below ~600px so a single long word ("lantraskaninen.",
    // "Mellerudskanin") fits a 375px column (ADR-0010, 375-px-kravet); the max equals
    // the token size, so nothing changes from tablet up. Mirrors tokens.css.
    h2: {
      fontFamily: displayFont,
      textWrap: "balance",
      fontSize: "clamp(36px, 9.6vw, 56px)",
      lineHeight: 1.06,
      letterSpacing: "-0.018em",
      fontWeight: 400,
    },
    h3: {
      fontFamily: displayFont,
      textWrap: "balance",
      fontSize: "clamp(28px, 7.5vw, 40px)",
      lineHeight: 1.1,
      letterSpacing: "-0.015em",
      fontWeight: 400,
    },
    h4: {
      fontFamily: displayFont,
      textWrap: "balance",
      fontSize: "clamp(24px, 6.4vw, 32px)",
      lineHeight: 1.15,
      letterSpacing: "-0.01em",
      fontWeight: 500,
    },
    h5: {
      fontFamily: bodyFont,
      fontSize: "24px",
      lineHeight: 1.25,
      fontWeight: 600,
    },
    h6: {
      fontFamily: bodyFont,
      fontSize: "20px",
      lineHeight: 1.3,
      fontWeight: 600,
    },
    body1: { fontSize: "16px", lineHeight: 1.55, textWrap: "pretty" },
    body2: { fontSize: "14px", lineHeight: 1.55 },

    display: {
      fontFamily: displayFont,
      fontWeight: 400,
      letterSpacing: "-0.02em",
      lineHeight: 1.08,
    },
    displayItalic: {
      fontFamily: displayFont,
      fontStyle: "italic",
      fontWeight: 400,
    },
    eyebrow: {
      fontFamily: monoFont,
      fontSize: "12px",
      textTransform: "uppercase" as const,
      letterSpacing: "0.16em",
      color: "#5A554B",
      fontWeight: 500,
    },
    lede: {
      fontSize: "20px",
      lineHeight: 1.5,
      color: "#3D362C",
    },
    mono: {
      fontFamily: monoFont,
      fontSize: "12px",
      color: "#6F6A5F",
      letterSpacing: "0.02em",
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: "#F4F1EA",
          fontFeatureSettings: "'ss01', 'cv11'",
          WebkitFontSmoothing: "antialiased",
          textRendering: "optimizeLegibility",
          "& ::selection": { background: "#2F4A32", color: "#F4F1EA" },
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      variants: [
        {
          props: { variant: "contained", color: "primary" },
          style: {
            backgroundColor: "#2F4A32",
            color: "#fff",
            border: "1px solid #2F4A32",
            "&:hover": {
              backgroundColor: "#1F3322",
              borderColor: "#1F3322",
            },
          },
        },
        {
          props: { variant: "outlined", color: "primary" },
          style: {
            backgroundColor: "transparent",
            color: "#1F1B16",
            border: "1px solid #B8AE99",
            "&:hover": {
              backgroundColor: "#EBE6D8",
              borderColor: "#1F1B16",
            },
          },
        },
      ],
      styleOverrides: {
        root: {
          fontFamily: bodyFont,
          fontWeight: 500,
          fontSize: "15px",
          padding: "12px 20px",
          borderRadius: "4px",
          minHeight: "44px",
          letterSpacing: "-0.005em",
          textTransform: "none" as const,
          transition:
            "transform 200ms cubic-bezier(0.2, 0.7, 0.2, 1), background 200ms cubic-bezier(0.2, 0.7, 0.2, 1), box-shadow 200ms cubic-bezier(0.2, 0.7, 0.2, 1)",
          "&:active": { transform: "translateY(1px)" },
        },
        text: {
          color: "#1F1B16",
          "&:hover": { backgroundColor: "#EBE6D8" },
        },
        sizeSmall: {
          padding: "8px 14px",
          fontSize: "13px",
          minHeight: "36px",
          // ADR-0010, 375-px-kravet: 44px tap target on touch screens.
          "@media (pointer: coarse)": { minHeight: "44px" },
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        // ADR-0010, 375-px-kravet: 44px tap target on touch screens.
        root: {
          "@media (pointer: coarse)": { minWidth: "44px", minHeight: "44px" },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundColor: "#FBF9F3",
          border: "1px solid #D7CFBE",
          borderRadius: "8px",
          boxShadow: "none",
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: { borderColor: "#D7CFBE" },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontFamily: monoFont,
          fontSize: "11px",
          letterSpacing: "0.06em",
          textTransform: "uppercase" as const,
          borderRadius: "4px",
          "&.MuiChip-colorDefault": {
            backgroundColor: "#EBE6D8",
            color: "#3D362C",
            border: "1px solid #D7CFBE",
          },
          "&.MuiChip-colorSuccess": {
            backgroundColor: "#E2E8D5",
            color: "#44602f",
            border: "1px solid #c8d3b3",
          },
          "&.MuiChip-colorError": {
            backgroundColor: "#F0D4CC",
            color: "#A23A2A",
            border: "1px solid #e6c0ad",
          },
          "&.MuiChip-colorWarning": {
            backgroundColor: "#F2E4C2",
            color: "#B98019",
            border: "1px solid #D7CFBE",
          },
          "&.MuiChip-colorInfo": {
            backgroundColor: "#D8E1E5",
            color: "#4A6B7A",
            border: "1px solid #c0cdd2",
          },
          "&.MuiChip-colorSecondary": {
            backgroundColor: "#F3DDD0",
            color: "#8a3f1f",
            border: "1px solid #e6c0ad",
          },
          "&.MuiChip-colorPrimary": {
            backgroundColor: "#D7DFCF",
            color: "#2F4A32",
            border: "1px solid #c0ccb4",
          },
        },
      },
    },
    MuiLink: {
      styleOverrides: {
        root: {
          color: "#1F1B16",
          textDecorationColor: "#B8AE99",
          textUnderlineOffset: "3px",
          textDecorationThickness: "1px",
          transition: "text-decoration-color 200ms",
          "&:hover": { textDecorationColor: "#B85C38" },
        },
      },
    },
    MuiDataGrid: {
      defaultProps: {
        density: "compact" as const,
      },
      styleOverrides: {
        root: {
          border: "1px solid #D7CFBE",
          backgroundColor: "#FBF9F3",
          borderRadius: "8px",
          fontSize: "14px",
          "--DataGrid-rowBorderColor": "#E5DECB",
          "--DataGrid-containerBackground": "#EBE6D8",
        },
        columnHeaderTitle: {
          fontFamily: monoFont,
          fontSize: "11px",
          fontWeight: 500,
          textTransform: "uppercase" as const,
          letterSpacing: "0.08em",
          color: "#6F6A5F",
        },
        toolbarContainer: {
          padding: "8px 12px",
          borderBottom: "1px solid #E5DECB",
        },
        footerContainer: {
          borderTop: "1px solid #D7CFBE",
          backgroundColor: "#F4F1EA",
        },
        row: {
          "&:hover": { backgroundColor: "#EBE6D8" },
        },
        columnHeaders: {
          borderBottom: "1px solid #B8AE99",
        },
        columnHeader: {
          paddingLeft: "12px",
          paddingRight: "12px",
          "&.MuiDataGrid-columnHeader--sorted .MuiDataGrid-columnHeaderTitle": {
            color: "#1F1B16",
          },
        },
        cell: {
          fontSize: "13px",
          paddingLeft: "12px",
          paddingRight: "12px",
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: {
          minHeight: "48px",
          borderBottom: "1px solid #D7CFBE",
        },
        indicator: {
          backgroundColor: "#2F4A32",
          height: "2px",
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: "none" as const,
          fontSize: "14px",
          fontWeight: 400,
          color: "#6F6A5F",
          minHeight: "48px",
          "&.Mui-selected": {
            color: "#1F1B16",
            fontWeight: 600,
          },
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        // Scrim: warm ink (--sb-ink #1F1B16) at 44%, not MUI's cold black 50%.
        // Scoped to the Dialog root so Drawer/Popover backdrops are untouched.
        root: {
          "& > .MuiBackdrop-root": {
            backgroundColor: "rgba(31,27,22,0.44)",
          },
        },
        // Same surface as MuiCard (:193-202): --sb-card on 1px --sb-line,
        // radius 8px (--sb-r-3), flat — the scrim carries the elevation.
        paper: {
          backgroundColor: "#FBF9F3",
          border: "1px solid #D7CFBE",
          borderRadius: "8px",
          boxShadow: "none",
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: "#F4F1EA",
          borderRadius: "4px",
          fontFamily: bodyFont,
          fontSize: "15px",
          // ADR-0010, 375-px-kravet: iOS zooms into fields under 16px on focus.
          // The Select's own div is the tap target, so its line box fills 44px.
          "@media (pointer: coarse)": {
            fontSize: "16px",
            "& .MuiSelect-select": { lineHeight: "24px" },
          },
          // .sb-input min-height 44 (tokens.css:237). The notched outline is an
          // absolutely-positioned <fieldset>, so its border adds 0 to layout —
          // padding alone yields 41.6px. The root is a centering flex box, so
          // min-height both restores the 44px target and lands the input text
          // at the 11px the resting label transform below assumes.
          minHeight: "44px",
          "& .MuiOutlinedInput-notchedOutline": { borderColor: "#B8AE99" },
          "&:hover:not(.Mui-error):not(.Mui-focused) .MuiOutlinedInput-notchedOutline":
            { borderColor: "#1F1B16" },
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: "#2F4A32",
            borderWidth: "2px",
          },
          "&.Mui-error .MuiOutlinedInput-notchedOutline": {
            borderColor: "#A23A2A",
          },
          "&.Mui-disabled": { backgroundColor: "#EBE6D8" },
        },
        // .sb-input horizontal padding (tokens.css:237); the root min-height
        // above carries the 44px.
        input: { padding: "10px 14px" },
        // .ad-search — 14px, 7px 12px, min-height 36 (Adminpanel.html:47).
        // MUI v9 dropped the `inputSizeSmall` slot; `sizeSmall` resolves onto
        // the root, so the inner input is reached by descendant selector.
        sizeSmall: {
          fontSize: "14px",
          minHeight: "36px",
          "& .MuiOutlinedInput-input": { padding: "7px 12px" },
          "@media (pointer: coarse)": {
            fontSize: "16px",
            minHeight: "44px",
            "& .MuiSelect-select": { lineHeight: "30px" },
          },
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        // Resting transform must follow the metrics above: min-height centring
        // starts the input text 11px (44px root) / 8px (36px root) below the
        // top edge. Measured, not derived — the outline fieldset adds no height.
        outlined: {
          color: "#6F6A5F",
          fontSize: "15px",
          transform: "translate(14px, 11px) scale(1)",
          "&.Mui-focused": { color: "#2F4A32" },
          "&.Mui-error": { color: "#A23A2A" },
          "&.MuiInputLabel-shrink": {
            transform: "translate(14px, -8px) scale(0.75)",
          },
          "&.MuiInputLabel-sizeSmall": {
            fontSize: "14px",
            transform: "translate(12px, 8px) scale(1)",
            "&.MuiInputLabel-shrink": {
              transform: "translate(12px, -8px) scale(0.75)",
            },
            // Small fields are 44px on touch screens (MuiOutlinedInput above).
            "@media (pointer: coarse)": {
              "&:not(.MuiInputLabel-shrink)": {
                transform: "translate(12px, 12px) scale(1)",
              },
            },
          },
        },
      },
    },
    MuiFormHelperText: {
      // Hints are 12px --sb-ink-3 (handoff README "Användare — detaljsida";
      // admin-ui.jsx:85 renders the inline switch hint at exactly these values).
      styleOverrides: {
        root: { fontSize: "12px", color: "#6F6A5F" },
      },
    },
    MuiSelect: {
      styleOverrides: {
        // 13px + 20px min-height inside the 7px small padding = 36px
        // (.ad-select, Adminpanel.html:50).
        select: {
          fontSize: "13px",
          minHeight: "20px",
          "@media (pointer: coarse)": { fontSize: "16px" },
        },
        icon: { color: "#6F6A5F" },
      },
    },
    MuiMenu: {
      styleOverrides: {
        paper: {
          backgroundColor: "#FBF9F3",
          border: "1px solid #D7CFBE",
          borderRadius: "8px",
          boxShadow:
            "0 2px 4px rgba(31,27,22,0.05), 0 6px 14px rgba(31,27,22,0.06)",
        },
        list: { paddingTop: "4px", paddingBottom: "4px" },
      },
    },
    MuiMenuItem: {
      styleOverrides: {
        root: {
          fontSize: "14px",
          // Self-compounded: MUI v9 emits MenuItem's `min-height: auto`
          // breakpoint rule after the theme styleOverrides, so a plain
          // `minHeight` here loses on order (measured 33.7px). 0-2-0 wins.
          "&.MuiMenuItem-root": { minHeight: "36px" },
          "@media (pointer: coarse)": {
            "&.MuiMenuItem-root": { minHeight: "44px" },
          },
          "&:hover": { backgroundColor: "#EBE6D8" },
          "&.Mui-selected": { backgroundColor: "#D7DFCF" },
          "&.Mui-selected:hover": { backgroundColor: "#D7DFCF" },
        },
      },
    },
    MuiAutocomplete: {
      styleOverrides: {
        paper: {
          backgroundColor: "#FBF9F3",
          border: "1px solid #D7CFBE",
          borderRadius: "8px",
          boxShadow:
            "0 2px 4px rgba(31,27,22,0.05), 0 6px 14px rgba(31,27,22,0.06)",
          marginTop: "4px",
        },
        // MUI v9 styles the rows from inside the listbox slot
        // (`.MuiAutocomplete-listbox .MuiAutocomplete-option`, 0-2-0), which
        // outranks the `option` slot (0-1-0) — so the row skin lives here to
        // land in the same class, after the base declarations.
        listbox: {
          padding: "4px 0",
          fontSize: "14px",
          "& .MuiAutocomplete-option": {
            minHeight: "36px",
            "@media (pointer: coarse)": { minHeight: "44px" },
            padding: "8px 12px",
            "&.Mui-focused": { backgroundColor: "#EBE6D8" },
            '&[aria-selected="true"]': { backgroundColor: "#D7DFCF" },
          },
        },
        noOptions: { fontSize: "14px", color: "#6F6A5F" },
        // Autocomplete owns the inner input padding, so the 36px floor is set
        // on the wrapper rather than via inputSizeSmall above.
        inputRoot: {
          "&.MuiInputBase-sizeSmall": { minHeight: "36px", paddingLeft: "8px" },
          "@media (pointer: coarse)": {
            "&.MuiInputBase-sizeSmall": { minHeight: "44px" },
          },
        },
        // The whole field opens the list, so the indicators keep their size
        // inside it instead of taking the 44px IconButton floor.
        popupIndicator: {
          "@media (pointer: coarse)": { minWidth: 0, minHeight: 0 },
        },
        clearIndicator: {
          "@media (pointer: coarse)": { minWidth: 0, minHeight: 0 },
        },
      },
    },
    MuiSwitch: {
      defaultProps: { disableRipple: true },
      styleOverrides: {
        root: { width: 40, height: 22, padding: 0 },
        switchBase: {
          padding: 3,
          "&:hover": { backgroundColor: "transparent" },
          "&.Mui-checked": {
            transform: "translateX(18px)",
            "& + .MuiSwitch-track": {
              backgroundColor: "#2F4A32",
              borderColor: "#2F4A32",
              opacity: 1,
            },
            "& .MuiSwitch-thumb": { borderColor: "#2F4A32" },
          },
          "&.Mui-disabled + .MuiSwitch-track": { opacity: 0.5 },
        },
        thumb: {
          width: 16,
          height: 16,
          boxSizing: "border-box",
          backgroundColor: "#fff",
          border: "1px solid #B8AE99",
          boxShadow: "none",
        },
        track: {
          borderRadius: "999px",
          boxSizing: "border-box",
          backgroundColor: "#EBE6D8",
          border: "1px solid #B8AE99",
          opacity: 1,
          transition:
            "background-color 200ms cubic-bezier(0.2, 0.7, 0.2, 1), border-color 200ms cubic-bezier(0.2, 0.7, 0.2, 1)",
        },
      },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        root: {
          "&:has(> .MuiSwitch-root)": {
            marginLeft: 0,
            marginRight: 0,
            gap: "12px",
            alignItems: "center",
          },
          "&:has(> .MuiSwitch-root) > .MuiFormControlLabel-label": {
            fontSize: "14px",
            fontWeight: 500,
          },
        },
      },
    },
    MuiTable: {
      styleOverrides: {
        root: { backgroundColor: "#FBF9F3" },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        // .ad-table td — 13px, 7px 12px, --sb-line-faint hairline
        root: {
          fontSize: "13px",
          padding: "7px 12px",
          borderBottom: "1px solid #E5DECB",
        },
        // .ad-table th — mono 11px uppercase 0.08em on --sb-paper-2,
        // 9px 12px, 1px --sb-line-strong bottom rule
        head: {
          fontFamily: monoFont,
          fontSize: "11px",
          fontWeight: 500,
          textTransform: "uppercase" as const,
          letterSpacing: "0.08em",
          color: "#6F6A5F",
          backgroundColor: "#EBE6D8",
          padding: "9px 12px",
          borderBottom: "1px solid #B8AE99",
          whiteSpace: "nowrap" as const,
        },
        sizeSmall: {
          padding: "7px 12px",
          "&.MuiTableCell-head": { padding: "9px 12px" },
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        // Opt-in only (the `hover` prop) — a non-interactive table must not
        // suggest clickability. .ad-table tbody tr:hover, Adminpanel.html:57.
        hover: { "&:hover": { backgroundColor: "#EBE6D8" } },
      },
    },
  },
});

// Locale packs for MUI core + DataGrid + DatePickers, lifted from the old
// template theme's locale wiring (spec DS-05). de stays wired even though it has no dashboard
// UI entry.
const muiLocales: Record<string, object[]> = {
  sv: [svSE, dgSvSE, dpSvSE],
  en: [enUS, dgEnUS, dpEnUS],
  de: [deDE, dgDeDE, dpDeDE],
};

/**
 * The one dashboard theme: the design-system stamboken theme with the MUI
 * sv/en/de locale packs merged in. Uses MUI's `createTheme(base, ...packs)`
 * merge so the base options object stays inline (no literal-widening).
 */
export function createStambokenTheme(locale: string = "sv"): Theme {
  const localeConfigs = muiLocales[locale] || muiLocales.sv;
  return createTheme(stambokenTheme, ...localeConfigs);
}

export default stambokenTheme;
