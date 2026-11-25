import Link from "next/link";
import { Box, Typography } from "@mui/material";
import type { Metadata } from "next";
import { LinkButton } from "@/components/public/LinkButton";
import { PageHeader } from "@/components/public/PageHeader";
import { MANUAL_PATH } from "@/lib/constants";

export const metadata: Metadata = {
  title: "Kom igång med Stamboken",
  description:
    "Från medlemskap till första kullen i Stamboken Online: konto, inloggning, testmiljön och de första stegen.",
};

// Plain style object, not MUI sx with component={Link}: see the note in
// bli-genbanksbesattning/page.tsx (an unserializable prop 500s the prod build).
const linkStyle = {
  color: "var(--sb-ink)",
  textDecoration: "underline",
  textDecorationColor: "var(--sb-line-strong)",
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
    title: "Ditt konto",
    text: "Du kan logga in med ditt föreningskonto eller med användarnamn och lösenord. Visas knappen Skicka kod kan du använda e-postadressen i matrikeln. Som huvudmedlem kan du då också skapa ett konto.",
    link: {
      href: "/kontoregler",
      label: "Läs reglerna för användarkonton",
    },
  },
  {
    title: "Logga in",
    text: "Klicka på Stamboken uppe till höger och sedan på Logga in i Stamboken. Välj ditt inloggningssätt. Använder du Google väljer du föreningskontot i Googles kontoväljare.",
    link: { href: `${MANUAL_PATH}#logga-in`, label: "Logga in steg för steg" },
  },
  {
    title: "Öva i testmiljön",
    text: "När du loggar in hamnar du i riktiga stamboken. Vill du prova något utan att ändra på riktigt kan du byta till testmiljön i menyn under din bild. Där kan du öva fritt, och allt återställs varje natt.",
    link: {
      href: `${MANUAL_PATH}#testmiljön-och-riktiga-stamboken`,
      label: "Om testmiljön",
    },
  },
  {
    title: "Registrera din första kull",
    text: "Under Min besättning ser du dina kaniner. Där registrerar du parningar och kullar, för kullistan och utfärdar digitala intyg till ungarna.",
    link: {
      href: `${MANUAL_PATH}#del-1--uppfödare`,
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
        lede="Från medlemskap till första kullen i Stamboken Online: konto, inloggning och de första stegen."
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
                // Desktop: number, title and text side by side, as on
                // Bli genbanksbesättning.
                gridTemplateColumns: {
                  xs: "40px 1fr",
                  md: "56px minmax(0, 300px) minmax(0, 1fr)",
                },
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
                  fontFamily: "var(--sb-display)",
                  fontSize: { xs: "20px", md: "26px" },
                  lineHeight: 1,
                }}
              >
                {i + 1}
              </Box>
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
              <Box
                sx={{
                  gridColumn: { xs: 2, md: 3 },
                  minWidth: 0,
                  maxWidth: "34rem",
                  pt: { md: 1 },
                }}
              >
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
          <Typography
            variant="h4"
            component="h3"
            sx={{ mt: 8, fontSize: { xs: "22px", md: "26px" } }}
          >
            Vad är på gång?
          </Typography>
          <Typography
            sx={{ mt: 3, color: "ink.2", fontSize: "15px", lineHeight: 1.65 }}
          >
            Vad föreningen arbetar med i Stamboken syns på{" "}
            <a
              href="https://github.com/orgs/gotlandskaninen/projects/1/views/3"
              style={linkStyle}
            >
              projekttavlan för Stamboken
            </a>{" "}
            på GitHub. Önskemål mejlar du till admin@gotlandskaninen.se, eller
            lämnar som ett ärende i{" "}
            <a
              href="https://github.com/gotlandskaninen/stamboken/issues"
              style={linkStyle}
            >
              gotlandskaninen/stamboken
            </a>
            . Allt på GitHub är offentligt, så skriv inga personuppgifter: inga
            namn, adresser eller besättningsnummer.
          </Typography>
          <Box sx={{ mt: 7, display: "flex", gap: 3, flexWrap: "wrap" }}>
            <LinkButton href={MANUAL_PATH} variant="contained">
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
