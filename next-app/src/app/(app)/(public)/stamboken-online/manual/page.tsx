import { readFile } from "node:fs/promises";
import path from "node:path";
import { Box } from "@mui/material";
import type { Metadata } from "next";
import { ManualArticle } from "@/components/manual/ManualArticle";
import { PageHeader } from "@/components/public/PageHeader";

export const metadata: Metadata = {
  title: "Manual för Stamboken",
  description:
    "Så använder du Stamboken Online: logga in, registrera kullar och kaniner, utfärda intyg, sälja och provpara.",
};

// The manual and its screenshots live together in public/, so the page, the
// raw file on GitHub and the Docker image all read the same copy.
const DIR = "/stamboken/manual/";
const ROOT = path.join(process.cwd(), "public", DIR);

export default async function ManualPage() {
  const markdown = await readFile(path.join(ROOT, "USER_MANUAL.md"), "utf8");

  return (
    <>
      <PageHeader
        section="Manual"
        parent={{ label: "Stamboken Online", href: "/stamboken-online" }}
        title="Manual för Stamboken"
        lede="Så använder du Stamboken: logga in, registrera kullar och kaniner, utfärda intyg, sälja och provpara."
      />
      <Box sx={{ px: { xs: 6, md: 14 }, py: { xs: 8, md: 12 } }}>
        <ManualArticle
          markdown={markdown}
          imageDir={ROOT}
          imageUrl={DIR}
          partsLabel="Manualens delar"
        />
      </Box>
    </>
  );
}
