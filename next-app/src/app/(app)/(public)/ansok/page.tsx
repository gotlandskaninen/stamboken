import { Box } from "@mui/material";
import { PageHeader } from "@/components/public/PageHeader";
import type { Metadata } from "next";
import { MembershipSteps } from "@/components/public/MembershipSteps";
import { ApplicationForm } from "./ApplicationForm";

export const metadata: Metadata = { title: "Ansök om medlemskap" };

export default function AnsokPage() {
  return (
    <>
      <PageHeader
        section="Bli medlem"
        title="Ansök om medlemskap"
        lede="Ansök om medlemskap i Föreningen Gotlandskaninen i formuläret nedan, eller med posten: betala årsavgiften till plusgirot och skriv namn och postadress på inbetalningen. Då är ansökan klar."
      />
      <Box component="section" sx={{ p: { xs: "40px 24px", md: "80px 56px" } }}>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              md: "minmax(0, 720px) minmax(260px, 380px)",
            },
            gap: { xs: 10, md: 14 },
            alignItems: "start",
          }}
        >
          {/* First in the source and on phones: read the steps, then fill in. */}
          <Box sx={{ order: { md: 2 } }}>
            <MembershipSteps />
          </Box>
          <ApplicationForm />
        </Box>
      </Box>
    </>
  );
}
