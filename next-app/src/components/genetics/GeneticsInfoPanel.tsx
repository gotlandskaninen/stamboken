import React from "react";
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

type TabName = "overview" | "priorities" | "breeding";

const descriptions: Record<TabName, { term: string; description: string }[]> = {
  overview: [
    {
      term: "Ne — Effektiv populationsstorlek",
      description:
        "Antal individer i en ideal population som ger samma genetiska drift som den verkliga populationen. Skattas från varje djurs inavelsökning per generation (Gutiérrez m.fl. 2008), över referenspopulationen, och beskriver takten sedan stamboken började. Riktmärken: FAO anger minst 50 på kort sikt; Frankham m.fl. 2014 minst 100.",
    },
    {
      term: "FGE — Founder genome-ekvivalenter",
      description:
        "Antal founders som skulle ge samma genetiska diversitet om de bidrog lika mycket. Baserat på gene drop-simulering (Lacy 1989). Högre FGE = bättre bevarad diversitet.",
    },
    {
      term: "Diversitetsförlust",
      description:
        "Andel av grundarnas genetiska variation som gått förlorad (= medelsläktskap i referenspopulationen). Motsvarar 1 − GD = 1/(2·FGE).",
    },
    {
      term: "MK — Genomsnittlig medelkinship",
      description:
        "Medelvärde av parvisa kinship-koefficienter bland aktiva individer. Lågt MK innebär mer genetisk diversitet i populationen.",
    },
    {
      term: "ΔF — Inavelsökningstakt per generation",
      description:
        "Hur snabbt inavel ökar per generation. FAO rekommenderar ΔF < 0.01 (1 %). Medelvärde av varje djurs inavelsökning per generation i referenspopulationen (Gutiérrez m.fl. 2008).",
    },
    {
      term: "F — Inavelskoefficient",
      description:
        "Sannolikhet att två alleler på ett locus är identiska genom härstamning (identical by descent). Beräknas med Hendersons tabulärmetod.",
    },
  ],
  priorities: [
    {
      term: "Genetiskt värde",
      description:
        "Inverterad MK-percentil (0–100). Individer med högt genetiskt värde har låg medelkinship, dvs. de är genetiskt ovanliga och därför värdefulla för bevarandearbetet.",
    },
    {
      term: "Genomunikhet",
      description:
        "Sannolikhet att individen bär alleler som inte finns hos andra i populationen. Beräknas från gene drop-simulering. Hög genomunikhet = individen har unika genetiska bidrag.",
    },
    {
      term: "Prioritetsnivåer",
      description:
        "Kritisk: enda bärare av en founder-linje eller MK under 5:e percentilen. Viktig: MK under 25:e percentilen, hög genomunikhet, eller bärare av underrepresenterad founder. Normal: övriga.",
    },
  ],
  breeding: [
    {
      term: "ΔGD — Förändring i gendiversitet",
      description:
        "Förändring i populationens gendiversitet om paret paras. Positivt värde innebär förbättrad diversitet. Beräknas utifrån kinship-matrisen.",
    },
    {
      term: "MSI — Mate Suitability Index",
      description:
        "Skala 1–6 där 1 = utmärkt och 6 = dålig. Baserat på förväntad inavel hos avkomma och påverkan på gendiversitet (Pollak et al., PMx).",
    },
    {
      term: "Förväntad F",
      description:
        "Förväntad inavelskoefficient hos avkomma. Lika med kinship-koefficienten mellan föräldrarna. Lägre = bättre.",
    },
    {
      term: "Max antal par / Max inavel / Max per hane",
      description:
        "Parametrar som styr optimeringen. Max inavel sätter övre gräns för tillåten avkomma-inavel. Max per hane begränsar överanvändning av enskilda hanar.",
    },
  ],
};

interface GeneticsInfoPanelProps {
  tab: TabName;
}

const GeneticsInfoPanel = ({ tab }: GeneticsInfoPanelProps) => {
  const items = descriptions[tab];
  if (!items) return null;

  return (
    <Accordion disableGutters sx={{ mb: 4, "&::before": { display: "none" } }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2">Förklaringar</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0 }}>
        <Table size="small">
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.term}>
                <TableCell
                  sx={{ fontWeight: 600, whiteSpace: "nowrap", width: "30%" }}
                >
                  {item.term}
                </TableCell>
                <TableCell>{item.description}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </AccordionDetails>
    </Accordion>
  );
};

export default GeneticsInfoPanel;
