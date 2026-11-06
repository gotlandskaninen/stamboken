import "@mui/material/styles";

declare module "@mui/material/styles" {
  interface PaletteColor {
    soft?: string;
    deep?: string;
  }

  interface SimplePaletteColorOptions {
    soft?: string;
    deep?: string;
  }

  interface Palette {
    skog: PaletteColor;
    mossa: PaletteColor;
    lera: PaletteColor;
    himmel: PaletteColor;
    paper: {
      main: string;
      "2": string;
      "3": string;
    };
    card: string;
    ink: {
      main: string;
      "2": string;
      "3": string;
      "4": string;
    };
    line: {
      main: string;
      strong: string;
      faint: string;
    };
  }

  interface PaletteOptions {
    skog?: SimplePaletteColorOptions;
    mossa?: SimplePaletteColorOptions;
    lera?: SimplePaletteColorOptions;
    himmel?: SimplePaletteColorOptions;
    paper?: {
      main: string;
      "2": string;
      "3": string;
    };
    card?: string;
    ink?: {
      main: string;
      "2": string;
      "3": string;
      "4": string;
    };
    line?: {
      main: string;
      strong: string;
      faint: string;
    };
  }

  interface TypographyVariants {
    display: React.CSSProperties;
    displayItalic: React.CSSProperties;
    eyebrow: React.CSSProperties;
    lede: React.CSSProperties;
    mono: React.CSSProperties;
  }

  interface TypographyVariantsOptions {
    display?: React.CSSProperties;
    displayItalic?: React.CSSProperties;
    eyebrow?: React.CSSProperties;
    lede?: React.CSSProperties;
    mono?: React.CSSProperties;
  }
}

declare module "@mui/material/Typography" {
  interface TypographyPropsVariantOverrides {
    display: true;
    displayItalic: true;
    eyebrow: true;
    lede: true;
    mono: true;
  }
}
