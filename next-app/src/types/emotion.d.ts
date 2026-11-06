import type { Theme as MuiTheme } from "@mui/material/styles";

// Emotion's `styled`/`withTheme` expose the MUI theme.
declare module "@emotion/react" {
  export interface Theme extends MuiTheme {}
}
