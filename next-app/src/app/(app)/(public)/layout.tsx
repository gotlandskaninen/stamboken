import { ReactNode } from "react";
import { Box } from "@mui/material";
import { StambokenThemeProvider } from "@/components/public/StambokenThemeProvider";
import { PublicNav } from "@/components/public/PublicNav";
import { PublicFooter } from "@/components/public/PublicFooter";

export const dynamic = "force-dynamic";

export const metadata = {
  title: {
    template:
      "%s | Föreningen Gotlandskaninen – bevarande av svenska lantraskaniner",
    default: "Föreningen Gotlandskaninen – bevarande av svenska lantraskaniner",
  },
  description:
    "Föreningen Gotlandskaninen bevarar gotlandskanin och mellerudskanin – utrotningshotade svenska husdjursraser – genom EU-stödd genbanksverksamhet sedan 1984.",
  keywords: [
    "gotlandskanin",
    "mellerudskanin",
    "lantraskanin",
    "genbank",
    "kaninavel",
    "bevarande",
    "föreningen gotlandskaninen",
  ],
  authors: [
    { name: "Föreningen Gotlandskaninen", url: "https://gotlandskaninen.se/" },
  ],
  metadataBase: new URL("https://gotlandskaninen.se"),
};

export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <Box>
      <StambokenThemeProvider>
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            minHeight: "100vh",
          }}
        >
          <PublicNav />
          <Box component="main" sx={{ flexGrow: 1 }}>
            {children}
          </Box>
          <PublicFooter />
        </Box>
      </StambokenThemeProvider>
    </Box>
  );
}
