import Link from "next/link";
import { Box, Typography } from "@mui/material";
import type { Metadata } from "next";
import { Icon, ICONS } from "@/components/public/Icons";
import { LinkButton } from "@/components/public/LinkButton";
import { OrnamentDivider } from "@/components/public/OrnamentDivider";
import { PageHeader } from "@/components/public/PageHeader";

export const metadata: Metadata = {
  title: "Bli genbanksbesättning",
  description:
    "Så blir du genbanksbesättning för gotlandskanin eller mellerudskanin: kraven, de fem stegen fram till godkänt kontrakt och vad som gäller år för år.",
};

const GOTLAND_MAIL = "gotlandskanin@gotlandskaninen.se";
const MELLERUD_MAIL = "mellerudskanin@gotlandskaninen.se";

// Inline <Link> gets a plain style object rather than MUI's sx: passing
// `component={Link}` to a MUI component from a Server Component sends an
// unserializable function prop across the RSC boundary and 500s the production
// build (dev and tsc stay green, so it only shows up after a prod build).
const inlineLinkStyle = {
  color: "#1F1B16",
  textDecoration: "underline",
  textDecorationColor: "#B8AE99",
  textUnderlineOffset: "3px",
};

const mailLinkSx = {
  color: "ink.main",
  fontSize: "15px",
  textDecoration: "underline",
  textDecorationColor: "line.strong",
  textUnderlineOffset: "3px",
  wordBreak: "break-word",
  "&:hover": { textDecorationColor: "lera.main" },
} as const;

const REQUIREMENTS = [
  {
    title: "Du är medlem i föreningen",
    desc: "Medlemskapet kostar 200 kr om året och gäller hela familjen. Betala till Plusgiro 35 03 44-8 eller Swish 123 095 70 50.",
  },
  {
    title: "Du har både hane och hona",
    desc: "En genbanksbesättning ska ha minst en hane. Honor och en lånad hane räcker inte.",
  },
  {
    title: "Du köper avelsdjur inom genbanken",
    desc: "Nya avelsdjur kommer från andra genbanksbesättningar i föreningen, aldrig utifrån.",
  },
  {
    title: "Du parar för variationen",
    desc: "Inte för färg, teckning eller vikt. Lynne, hälsa och reproduktion går före utseende.",
  },
  {
    title: "Du håller ordning",
    desc: "Intyg på alla avelsdjur, kullarna dokumenterade och en årsrapport varje år.",
  },
];

const STEPS: Array<{
  title: string;
  body: string[];
  links?: Array<{ href: string; label: string }>;
}> = [
  {
    title: "Bli medlem",
    body: [
      "Betala medlemsavgiften, så är du med i föreningen. Ansökan fyller du i på webben och avgiften gäller hela familjen.",
    ],
    links: [{ href: "/bli-medlem", label: "Bli medlem →" }],
  },
  {
    title: "Kontakta genbanksansvarig",
    body: [
      "Mejla genbanksansvarig för den ras du vill föda upp och be om ansökningshandlingarna: en instruktion om ansökan och avel, själva genbankskontraktet i två exemplar och en bilaga.",
      "Ofta följer handlingarna redan med välkomstbrevet till nya medlemmar.",
    ],
    links: [
      { href: `mailto:${GOTLAND_MAIL}`, label: GOTLAND_MAIL },
      { href: `mailto:${MELLERUD_MAIL}`, label: MELLERUD_MAIL },
    ],
  },
  {
    title: "Skaffa startdjur",
    body: [
      "Du behöver minst en hane och en hona med genbanksintyg, köpta från befintliga genbanksbesättningar. Intygen följer med djuren.",
      "Genbanksansvarig och tidskriften Koharen hjälper dig hitta uppfödare som har djur att sälja.",
    ],
  },
  {
    title: "Skicka in ansökan",
    body: [
      "Skicka båda exemplaren av kontraktet ifyllda, tillsammans med kopior på djurens genbanksintyg, bilder och en kort beskrivning av besättningen.",
      "Genbanksansvarig går igenom underlaget och provparar dina startdjur i Stamboken Online för att se inavelsgraden. Under 4 procent är bra, över 6 procent utreds närmare. Räkna med några kompletteringar fram och tillbaka.",
    ],
  },
  {
    title: "Godkännande",
    body: [
      "Du får tillbaka ditt exemplar av kontraktet, undertecknat av båda parter, och ett startpaket: välkomstbrev, rasram, infoblad om märkning och tillstånd, enkla mallar för att hålla ordning i aveln, fem genbanksintyg och några skötselhäften.",
      "Ditt besättningsnummer är detsamma som ditt medlemsnummer: G123 för gotlandskanin, M123 för mellerudskanin. Sedan läggs besättningen in i Stamboken Online.",
    ],
  },
];

const YEARLY = [
  {
    icon: ICONS.pedigree,
    title: "Para och dokumentera",
    desc: "Följ avelsråden och undvik att para nära släkt. En testparning i Stamboken Online visar släktskapet i förväg.",
  },
  {
    icon: ICONS.shield,
    title: "Intyg på varje avelsdjur",
    desc: "Alla djur som säljs som avelsdjur ska ha genbanksintyg. En kanin utan intyg är en förlorad kanin för bevarandearbetet. Pappersintyg kostar 5 kr styck, och fem ingår vid godkännandet. I Stamboken Online är intyget gratis.",
  },
  {
    icon: ICONS.book,
    title: "Årsrapport senast 31 januari",
    desc: "Sedan 2024 lämnar du den direkt i Stamboken Online. Årsrapporten är också grunden för Jordbruksverkets stöd, som kräver minst en kull under året, hane och hona vid årsskiftet och betald medlemsavgift.",
  },
];

// Who holds the role is CMS content (the Styrelse och kontakt page), not
// source: names change with the board and must not live in a public repo.
const CONTACTS = [
  { breed: "Gotlandskanin", mail: GOTLAND_MAIL },
  { breed: "Mellerudskanin", mail: MELLERUD_MAIL },
];

function SectionHeading({
  eyebrow,
  title,
}: {
  eyebrow: string;
  title: string;
}) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: "minmax(80px, 160px) 1fr" },
        gap: { xs: 4, md: 8 },
        mb: 9,
      }}
    >
      <Typography variant="eyebrow">{eyebrow}</Typography>
      <Typography variant="h2" sx={{ m: 0 }}>
        {title}
      </Typography>
    </Box>
  );
}

function IntroSection() {
  return (
    <Box
      component="section"
      sx={{ px: { xs: 6, md: 14 }, pt: { xs: 10, md: 16 }, pb: 8 }}
    >
      <Box
        sx={{
          bgcolor: "skog.soft",
          borderRadius: "8px",
          p: { xs: 6, md: 11 },
          maxWidth: 820,
        }}
      >
        <Typography variant="h2" sx={{ m: 0 }}>
          {/* Soft hyphen: "genbanksbesättning" is wider than a 375px column at
              the h2 size, so it has to be allowed to break (ADR-0010, 375-px-kravet).
              Same trick as the landing page's "Medlems&shy;verksamhet". */}
          {"Vad en genbanks\u00ADbesättning är"}
        </Typography>
        <Typography variant="lede" sx={{ mt: 4, display: "block" }}>
          En genbank ska bevara så mycket som möjligt av rasens arvsanlag. Man
          sorterar inte bort anlag genom snäva urval, bara rena defekter, och
          korsar inte in andra raser. Alla djur är registrerade med
          genbanksintyg och härstammar från de kaniner som inventerades 1993
          (gotlandskanin) respektive köptes ut 2001–2002 (mellerudskanin).
        </Typography>
        <Typography
          sx={{ mt: 5, maxWidth: "38rem", color: "ink.2", lineHeight: 1.65 }}
        >
          Genbanken är ett slutet system. Nya djur kommer in bara som avkommor
          till djur som redan finns där. En kanin utifrån går inte att föra in.
          Det är därför startdjuren måste komma från andra genbanksbesättningar
          i föreningen.
        </Typography>
        <Box sx={{ mt: 8, display: "flex", gap: 3, flexWrap: "wrap" }}>
          <LinkButton
            href="/bli-medlem"
            variant="contained"
            endIcon={<Icon d={ICONS.arrow} size={14} />}
          >
            Bli medlem
          </LinkButton>
          <Box
            component="a"
            href={`mailto:${GOTLAND_MAIL}`}
            sx={{
              display: "inline-flex",
              alignItems: "center",
              gap: 2,
              minHeight: "44px",
              px: 5,
              py: 3,
              borderRadius: "4px",
              border: "1px solid #B8AE99",
              color: "ink.main",
              fontSize: "15px",
              fontWeight: 500,
              textDecoration: "none",
              "&:hover": { bgcolor: "paper.2", borderColor: "ink.main" },
            }}
          >
            <Icon d={ICONS.mail} size={15} />
            Mejla genbanksansvarig
          </Box>
        </Box>
        <Typography
          sx={{
            mt: 6,
            maxWidth: "36rem",
            fontSize: "15px",
            lineHeight: 1.65,
            color: "ink.2",
          }}
        >
          Mer om hur bevarandet fungerar finns under{" "}
          <Link href="/lantraskaninen" style={inlineLinkStyle}>
            Så fungerar genbanken
          </Link>
          . Själva registret heter{" "}
          <Link href="/stamboken-online" style={inlineLinkStyle}>
            Stamboken Online
          </Link>
          .
        </Typography>
      </Box>
    </Box>
  );
}

function RequirementsSection() {
  return (
    <Box
      component="section"
      sx={{ px: { xs: 6, md: 14 }, pt: { xs: 10, md: 14 }, pb: 8 }}
    >
      <SectionHeading eyebrow="Förutsättningar" title="Passar det dig?" />
      <Box
        sx={{
          bgcolor: "background.paper",
          border: 1,
          borderColor: "line.main",
          borderRadius: "8px",
          p: { xs: 5, md: 8 },
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
          gap: { xs: 5, md: 7 },
        }}
      >
        {REQUIREMENTS.map((req) => (
          <Box
            key={req.title}
            sx={{ display: "flex", gap: 3.5, alignItems: "flex-start" }}
          >
            <Box
              aria-hidden
              sx={{
                mt: 0.5,
                width: 28,
                height: 28,
                borderRadius: "50%",
                bgcolor: "mossa.soft",
                color: "skog.main",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Icon d={ICONS.check} size={15} stroke={2} />
            </Box>
            <Box>
              <Typography sx={{ fontWeight: 600, fontSize: "16px" }}>
                {req.title}
              </Typography>
              <Typography
                sx={{
                  mt: 1.5,
                  color: "ink.2",
                  fontSize: "15px",
                  lineHeight: 1.6,
                }}
              >
                {req.desc}
              </Typography>
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function StepsSection() {
  return (
    <Box
      component="section"
      sx={{ px: { xs: 6, md: 14 }, pt: { xs: 10, md: 14 }, pb: 8 }}
    >
      <SectionHeading eyebrow="Fem steg" title="Så går det till" />
      <Box
        component="ol"
        // listStyle:none drops list semantics in Safari/VoiceOver; keep them.
        role="list"
        sx={{
          listStyle: "none",
          m: 0,
          p: 0,
          maxWidth: 820,
          border: 1,
          borderColor: "line.main",
          borderRadius: "8px",
          bgcolor: "background.paper",
          px: { xs: 5, md: 9 },
        }}
      >
        {STEPS.map((step, i) => (
          <Box
            key={step.title}
            component="li"
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "40px 1fr", md: "56px 1fr" },
              columnGap: { xs: 4, md: 6 },
              alignItems: "start",
              py: { xs: 6, md: 8 },
              ...(i > 0 && { borderTop: 1, borderColor: "line.faint" }),
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
                component="h3"
                sx={{ m: 0, fontSize: { xs: "22px", md: "26px" } }}
              >
                {step.title}
              </Typography>
              {step.body.map((para) => (
                <Typography
                  key={para}
                  sx={{
                    mt: 3,
                    color: "ink.2",
                    fontSize: "15px",
                    lineHeight: 1.65,
                  }}
                >
                  {para}
                </Typography>
              ))}
              {step.links && (
                <Box
                  sx={{
                    mt: 4,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-start",
                    gap: 2,
                  }}
                >
                  {step.links.map((l) =>
                    l.href.startsWith("mailto:") ? (
                      <Box
                        key={l.href}
                        component="a"
                        href={l.href}
                        sx={{ ...mailLinkSx, fontSize: "14px" }}
                      >
                        {l.label}
                      </Box>
                    ) : (
                      <Link
                        key={l.href}
                        href={l.href}
                        style={{ ...inlineLinkStyle, fontSize: "15px" }}
                      >
                        {l.label}
                      </Link>
                    ),
                  )}
                </Box>
              )}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function YearlySection() {
  return (
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, pt: 8, pb: 8 }}>
      <SectionHeading eyebrow="Löpande arbete" title="Sedan, år för år" />
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 5,
        }}
      >
        {YEARLY.map((card) => (
          <Box
            key={card.title}
            sx={{
              bgcolor: "background.paper",
              border: 1,
              borderColor: "line.main",
              borderRadius: "8px",
              p: 7,
            }}
          >
            <Box
              aria-hidden
              sx={{
                width: 48,
                height: 48,
                borderRadius: "50%",
                bgcolor: "skog.soft",
                color: "skog.main",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                mb: 5,
              }}
            >
              <Icon d={card.icon} size={22} />
            </Box>
            <Typography
              variant="h4"
              component="h3"
              sx={{ m: 0, fontSize: "22px" }}
            >
              {card.title}
            </Typography>
            <Typography
              sx={{ mt: 3, color: "ink.2", fontSize: "15px", lineHeight: 1.6 }}
            >
              {card.desc}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function ContactSection() {
  return (
    <Box
      component="section"
      sx={{ px: { xs: 6, md: 14 }, pt: { xs: 10, md: 14 }, pb: 20 }}
    >
      <SectionHeading eyebrow="Kontakt" title="Hör av dig" />
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))" },
          gap: 6,
          maxWidth: 900,
        }}
      >
        {CONTACTS.map((c) => (
          <Box
            key={c.breed}
            sx={{
              bgcolor: "paper.2",
              border: 1,
              borderColor: "line.strong",
              borderRadius: "8px",
              p: { xs: 6, md: 7 },
            }}
          >
            {/* ink.2: the mono default (ink.3) is only 4.3:1 on paper.2 */}
            <Typography
              variant="mono"
              sx={{ display: "block", color: "ink.2" }}
            >
              Genbanksansvarig
            </Typography>
            <Typography
              variant="h4"
              component="h3"
              sx={{ mt: 2, mb: 0, fontSize: "24px" }}
            >
              {c.breed}
            </Typography>
            <Typography
              sx={{ mt: 3, color: "ink.2", fontSize: "15px", lineHeight: 1.6 }}
            >
              Vem som är genbanksansvarig just nu står under{" "}
              <Link href="/styrelsen" style={inlineLinkStyle}>
                Styrelse och kontakt
              </Link>
              .
            </Typography>
            <Box
              component="a"
              href={`mailto:${c.mail}`}
              sx={{ ...mailLinkSx, display: "inline-block", mt: 4 }}
            >
              {c.mail}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

export default function BliGenbankPage() {
  return (
    <>
      <PageHeader
        section="Lantraskaninen"
        // Soft hyphen so the compound word can break on a 375px screen; the
        // <title> and the e2e assertion use the plain spelling.
        title={"Bli genbanks\u00ADbesättning"}
        lede="Genbanksbesättningarna är kärnan i bevarandet. Så här blir du en av dem: vad som krävs, vem du kontaktar och hur ansökan går till."
        image={{
          src: "/stamboken/hero-ungar-gronfoder.jpg",
          alt: "Kaninungar i olika färger äter grönt på en bädd av halm",
          position: "50% 50%",
        }}
      />
      <IntroSection />
      <RequirementsSection />
      <StepsSection />
      <OrnamentDivider />
      <YearlySection />
      <ContactSection />
    </>
  );
}
