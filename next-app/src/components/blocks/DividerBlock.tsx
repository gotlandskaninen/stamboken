import { Box, Divider } from "@mui/material";

interface Props {
  style?: "line" | "space";
}

export function DividerBlockComponent({ style = "line" }: Props) {
  if (style === "space") {
    return <Box sx={{ height: 48 }} />;
  }
  return <Divider sx={{ my: 4 }} />;
}
