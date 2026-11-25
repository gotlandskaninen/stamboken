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

export const FOUNDERDJUR =
  "Founderdjur: rasens ursprungsdjur, kaniner utan kända föräldrar i stamboken.";

export const IN_CALCULATION =
  "Kaniner med intyg som lever, inte är kastrerade och står i en aktiv besättning i genbanken (inte GX1 eller MX1), och som har fötts, sålts eller årsrapporterats sedan 1 januari det år som den senast stängda årsrapporteringen gäller. Nyckeltalen och tabellerna räknas på dem; trenden räknar varje år på det årets kaniner.";

const founderdjur = {
  term: "Founderdjur",
  description:
    "Rasens ursprungsdjur: kaniner utan kända föräldrar i stamboken. En bärare av ett founderdjur är en kanin i beräkningen som har gener från det.",
};

const inCalculation = {
  term: "Kaniner i beräkningen",
  description: IN_CALCULATION,
};

const descriptions: Record<
  TabName,
  { term: string; description: string; source?: string }[]
> = {
  overview: [
    founderdjur,
    inCalculation,
    {
      term: "Effektiv populationsstorlek (Ne)",
      description:
        "Hur stor en idealisk population skulle vara för att förlora genetisk variation lika långsamt som genbanken. Ju större, desto bättre. Räknas från hur mycket inaveln har ökat per generation hos varje kanin, sedan stamboken började. Mål: minst 50, helst 100.",
      source:
        "Gutiérrez m.fl. 2008 (beräkningen), FAO (minst 50), Frankham m.fl. 2014 (minst 100)",
    },
    {
      term: "Effektivt antal founderdjur (FE)",
      description:
        "Så många founderdjur som, om alla hade lämnat lika stor andel av generna, skulle ge samma spridning av generna som i dag. Ju närmare antalet founderdjur, desto jämnare är generna fördelade. En okänd förälder till en kanin med bara en känd förälder räknas som ett eget founderdjur.",
      source: "Lacy 1989",
    },
    {
      term: "Medelsläktskap (MK)",
      description:
        "Hur nära släkt kaninerna i beräkningen i genomsnitt är med varandra, i procent. Det är också den andel av founderdjurens genetiska variation som har gått förlorad. Lägre är bättre.",
    },
    {
      term: "Inavelskoefficient (F)",
      description:
        "Hur inavlad en kanin är, i procent. Den blir högre ju närmare släkt föräldrarna är. Sidan visar genomsnittet för kaninerna i beräkningen.",
    },
    {
      term: "Inavelsökning per generation (ΔF)",
      description:
        "Hur mycket inaveln ökar per generation, i genomsnitt för kaninerna i beräkningen. Mål: under 1\u00a0%.",
      source: "Gutiérrez m.fl. 2008 (beräkningen), FAO (under 1\u00a0%)",
    },
  ],
  priorities: [
    founderdjur,
    inCalculation,
    {
      term: "Avelsprioritet",
      description:
        "Högsta: enda kaninen i beräkningen med gener från ett founderdjur, eller ett medelsläktskap på eller under gränsen för de 5\u00a0% minst släkta. Hög: på eller under gränsen för de 25\u00a0% minst släkta, bland de 25\u00a0% med flest unika gener, eller bär gener från ett founderdjur med liten andel av generna (under hälften av en jämn fördelning). Övriga: resten.",
      source: "Ballou och Lacy 1995 (rangordning efter medelsläktskap)",
    },
    {
      term: "Ovanliga gener (0–100)",
      description:
        "Hur stor andel av kaninerna i beräkningen som är mer släkt med resten än den här kaninen. 100 betyder minst släkt, alltså mest ovanliga gener.",
    },
    {
      term: "Unika gener",
      description:
        "Sannolikheten att kaninen bär genvarianter från founderdjuren som ingen annan kanin i beräkningen bär, enligt en simulering av hur generna ärvs genom stamtavlan.",
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
                <TableCell>
                  {item.description}
                  {item.source && (
                    <Typography
                      variant="caption"
                      component="p"
                      color="textSecondary"
                      sx={{ mt: 0.5 }}
                    >
                      Källa: {item.source}
                    </Typography>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </AccordionDetails>
    </Accordion>
  );
};

export default GeneticsInfoPanel;
