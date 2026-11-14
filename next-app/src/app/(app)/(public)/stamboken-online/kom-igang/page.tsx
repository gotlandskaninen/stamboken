import Link from "next/link";
import { Box, Typography } from "@mui/material";
import type { Metadata } from "next";
import { LinkButton } from "@/components/public/LinkButton";
import { PageHeader } from "@/components/public/PageHeader";
import { COURSE_URL } from "@/lib/constants";

export const metadata: Metadata = {
  title: "Kom igång med Stamboken",
  description:
    "Från medlemskap till första kullen i Stamboken Online: föreningskonto, webbkurs, inloggning, testmiljön och de första stegen.",
};

const MANUAL = "/stamboken-online/manual";

// Plain style object, not MUI sx with component={Link}: see the note in
// bli-genbanksbesattning/page.tsx (an unserializable prop 500s the prod build).
const linkStyle = {
  color: "#1F1B16",
  textDecoration: "underline",
  textDecorationColor: "#B8AE99",
  textUnderlineOffset: "3px",
};

const STEPS: Array<{
  title: string;
  text: string;
  link: { href: string; label: string };
}> = [
  {
    title: "Bli genbanksbesättning",
    text: "Det är föreningens genbanksbesättningar som för in sina kaniner i Stamboken. När ditt genbankskontrakt är godkänt lägger genbanksansvarig in besättningen, med ditt besättningsnummer.",
    link: {
      href: "/bli-genbanksbesattning",
      label: "Så blir du genbanksbesättning",
    },
  },
  {
    title: "Ditt föreningskonto",
    text: "Som medlem får du ett föreningskonto: en e-postadress på gotlandskaninen.se som föreningen skapar åt dig. Samma konto används i medlemsforumet. Har du användarnamn och lösenord från gamla Stamboken fungerar de också.",
    link: { href: "/medlemsforum", label: "Medlemsforumet" },
  },
  {
    title: "Gå webbkursen",
    text: "Föreningens webbkurs går igenom stamboken och genbanksarbetet. När du har gått den markerar administratören ditt konto som validerat. Först då släpper inloggningen med föreningskontot in dig.",
    link: { href: COURSE_URL, label: "Till webbkursen" },
  },
  {
    title: "Logga in",
    text: "Gå till gotlandskaninen.se/stamboken och klicka på Logga in med ditt föreningskonto (Google). Välj föreningskontot i Googles kontoväljare, inte ett privat Gmail-konto. Har du inget föreningskonto loggar du in med användarnamn och lösenord.",
    link: { href: `${MANUAL}#logga-in`, label: "Logga in steg för steg" },
  },
  {
    title: "Öva i testmiljön",
    text: "Nya användare börjar i testmiljön, en kopia av stamboken som återställs varje natt. Där kan du prova allt utan att något sparas på riktigt. När administratören har gett dig tillgång byter du till riktiga stamboken i menyn under din bild.",
    link: {
      href: `${MANUAL}#testmiljön-och-riktiga-stamboken`,
      label: "Om testmiljön",
    },
  },
  {
    title: "Registrera din första kull",
    text: "Under Min besättning ser du dina kaniner. Där registrerar du parningar och kullar, för kullistan och utfärdar digitala intyg till ungarna.",
    link: {
      href: `${MANUAL}#del-1--uppfödare`,
      label: "Manualen för uppfödare",
    },
  },
];

export default function KomIgangPage() {
  return (
    <>
      <PageHeader
        section="Kom igång"
        parent={{ label: "Stamboken Online", href: "/stamboken-online" }}
        title="Kom igång med Stamboken"
        lede="Från medlemskap till första kullen i Stamboken Online: föreningskonto, webbkurs, inloggning och de första stegen."
      />
      <Box
        component="section"
        sx={{ px: { xs: 6, md: 14 }, pt: { xs: 10, md: 14 }, pb: 8 }}
      >
        <Box
          component="ol"
          // listStyle:none drops list semantics in Safari/VoiceOver; keep them.
          role="list"
          sx={{
            listStyle: "none",
            m: 0,
            p: 0,
            maxWidth: "52rem",
            borderBottom: 1,
            borderColor: "line.main",
          }}
        >
          {STEPS.map((step, i) => (
            <Box
              key={step.title}
              component="li"
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "40px 1fr", md: "56px 1fr" },
                columnGap: { xs: 4, md: 8 },
                alignItems: "start",
                py: { xs: 6, md: 7 },
                borderTop: 1,
                borderColor: "line.main",
              }}
            >
              <Box
                aria-hidden
                sx={{
                  width: { xs: 40, md: 56 },
                  height: { xs: 40, md: 56 },
                  borderRadius: "50%",
                  bgcolor: "skog.soft",
                  color: "skog.main",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "'Source Serif 4', Georgia, serif",
                  fontSize: { xs: "20px", md: "26px" },
                  lineHeight: 1,
                }}
              >
                {i + 1}
              </Box>
              <Box sx={{ minWidth: 0 }}>
                <Typography
                  variant="h4"
                  component="h2"
                  sx={{
                    m: 0,
                    pt: { xs: 1.5, md: 3 },
                    fontSize: { xs: "22px", md: "26px" },
                  }}
                >
                  {step.title}
                </Typography>
                <Typography
                  sx={{
                    mt: 3,
                    color: "ink.2",
                    fontSize: "15px",
                    lineHeight: 1.65,
                  }}
                >
                  {step.text}
                </Typography>
                <Typography sx={{ mt: 3, fontSize: "15px" }}>
                  <Link href={step.link.href} style={linkStyle}>
                    {step.link.label} →
                  </Link>
                </Typography>
              </Box>
            </Box>
          ))}
        </Box>
      </Box>
      <Box
        component="section"
        sx={{ px: { xs: 6, md: 14 }, pt: 8, pb: { xs: 12, md: 16 } }}
      >
        <Box sx={{ maxWidth: "52rem" }}>
          <Typography variant="h2" sx={{ m: 0 }}>
            Behöver du hjälp?
          </Typography>
          <Typography
            sx={{ mt: 4, color: "ink.2", fontSize: "15px", lineHeight: 1.65 }}
          >
            Manualen beskriver varje sida i Stamboken steg för steg. Frågor om
            aveln ställer du till genbanksansvarig för din ras:{" "}
            <a href="mailto:gotlandskanin@gotlandskaninen.se" style={linkStyle}>
              gotlandskanin@gotlandskaninen.se
            </a>{" "}
            eller{" "}
            <a
              href="mailto:mellerudskanin@gotlandskaninen.se"
              style={linkStyle}
            >
              mellerudskanin@gotlandskaninen.se
            </a>
            . Frågor om konto och inloggning går till{" "}
            <a href="mailto:admin@gotlandskaninen.se" style={linkStyle}>
              admin@gotlandskaninen.se
            </a>
            .
          </Typography>
          <Box sx={{ mt: 7, display: "flex", gap: 3, flexWrap: "wrap" }}>
            <LinkButton href={MANUAL} variant="contained">
              Läs manualen
            </LinkButton>
            <LinkButton href="/stamboken/min-besattning" variant="outlined">
              Logga in
            </LinkButton>
          </Box>
        </Box>
      </Box>
    </>
  );
}
