import { Box } from "@mui/material";
import { PageHeader } from "@/components/public/PageHeader";
import type { Metadata } from "next";
import { ApplicationForm } from "./ApplicationForm";

export const metadata: Metadata = { title: "Ansök om medlemskap" };

export default function AnsokPage() {
  return (
    <>
      <PageHeader
        section="Bli medlem"
        title="Ansök om medlemskap"
        lede="Fyll i formuläret nedan för att ansöka om medlemskap i Föreningen Gotlandskaninen."
      />
      <Box component="section" sx={{ p: { xs: "40px 24px", md: "80px 56px" } }}>
        <Box sx={{ maxWidth: 720 }}>
          <ApplicationForm />
        </Box>
      </Box>
    </>
  );
}
