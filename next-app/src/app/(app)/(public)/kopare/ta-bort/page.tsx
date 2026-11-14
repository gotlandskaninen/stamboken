import { Box } from "@mui/material";
import type { Metadata } from "next";
import { PageHeader } from "@/components/public/PageHeader";
import { EraseBuyer } from "./EraseBuyer";

export const metadata: Metadata = { title: "Ta bort dina uppgifter" };

/** The link in the mail to a buyer outside the association (kopare.information). */
export default function TaBortPage() {
  return (
    <>
      <PageHeader section="Dataskydd" title="Ta bort dina uppgifter" />
      <Box
        component="section"
        sx={{ p: { xs: "40px 24px", md: "80px 56px" }, maxWidth: 720 }}
      >
        <EraseBuyer />
      </Box>
    </>
  );
}
