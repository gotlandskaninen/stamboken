import { ReactNode } from "react";
import { Box } from "@mui/material";
import { StambokenThemeProvider } from "@/components/public/StambokenThemeProvider";

export const dynamic = "force-dynamic";

export const metadata = {
  title: {
    template: "%s | Stamboken Online",
    default: "Stamboken Online — Logga in",
  },
  description: "Logga in till Stamboken Online",
};

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <Box>
      <StambokenThemeProvider>
        <Box sx={{ minHeight: "100dvh", bgcolor: "paper.main" }}>
          {children}
        </Box>
      </StambokenThemeProvider>
    </Box>
  );
}
