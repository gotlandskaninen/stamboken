import Link from "next/link";
import { Box, Typography } from "@mui/material";
import type { Metadata } from "next";
import { Icon, ICONS } from "@/components/public/Icons";
import { LinkButton } from "@/components/public/LinkButton";
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
  "&:hover": { textDecorationColor: "lera.main" },
} as const;

const REQUIREMENTS = [
  {
    title: "Du är medlem i föreningen",
    desc: "Medlemskapet kostar 200 kr om året och gäller hela familjen.",
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
    title: "Para och dokumentera",
    desc: "Följ avelsråden och undvik att para nära släkt. En testparning i Stamboken Online visar släktskapet i förväg.",
  },
  {
    title: "Intyg på varje avelsdjur",
    desc: "Alla djur som säljs som avelsdjur ska ha genbanksintyg. En kanin utan intyg är en förlorad kanin för bevarandearbetet. Pappersintyg kostar 5 kr styck, och fem ingår vid godkännandet. I Stamboken Online är intyget gratis.",
  },
  {
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

// What sets a gene bank apart from ordinary breeding, beside the plain answer.
const RULES = [
  {
    title: "Slutet system",
    text: "Nya djur kommer bara in som avkommor till djur som redan finns i genbanken. Därför köper du startdjuren från andra genbanksbesättningar.",
  },
  {
    title: "Hela arvet bevaras",
    text: "Inga snäva urval och ingen inkorsning av andra raser. Bara rena defekter sorteras bort.",
  },
  {
    title: "Alla djur har intyg",
    text: "De härstammar från kaninerna som inventerades 1993 (gotlandskanin) eller köptes ut 2001–2002 (mellerudskanin).",
  },
];

const RULE_LINE = "1px solid rgba(31,27,22,0.16)";

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
          display: "grid",
          gridTemplateColumns: { md: "minmax(0, 1.1fr) minmax(0, 1fr)" },
          gap: { xs: 8, md: 14 },
        }}
      >
        <Box>
          <Typography variant="h2" sx={{ m: 0 }}>
            {/* Soft hyphen: "genbanksbesättning" is wider than a 375px column at
                the h2 size, so it has to be allowed to break (ADR-0010, 375-px-kravet).
                Same trick as the landing page's "Medlems&shy;verksamhet". */}
            {"Vad är en genbanks­besättning?"}
          </Typography>
          <Typography variant="lede" sx={{ mt: 4, display: "block" }}>
            En genbanksbesättning är kaniner som en medlem föder upp hemma, på
            avtal med föreningen. Stammen lever ute hos medlemmarna, inte i en
            byggnad eller ett museum.
          </Typography>
          <Box sx={{ mt: 7, display: "flex", gap: 3, flexWrap: "wrap" }}>
            <LinkButton
              href="/bli-medlem"
              variant="contained"
              endIcon={<Icon d={ICONS.arrow} size={14} />}
            >
              Bli medlem
            </LinkButton>
            <Box
              component="a"
              href="#kontakt"
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
              Kontakta genbanksansvarig
            </Box>
          </Box>
          <Typography
            sx={{
              mt: 5,
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
        <Box
          component="ul"
          sx={{
            listStyle: "none",
            m: 0,
            p: 0,
            // Full shorthands: a responsive `borderLeft: 1` resets the colour.
            borderTop: { xs: RULE_LINE, md: "none" },
            pt: { xs: 3, md: 0 },
            borderLeft: { md: RULE_LINE },
            pl: { md: 11 },
          }}
        >
          {RULES.map((rule, i) => (
            <Box
              component="li"
              key={rule.title}
              sx={{ py: 3.5, borderTop: i ? RULE_LINE : "none" }}
            >
              <Typography
                component="h3"
                sx={{ fontSize: "15px", fontWeight: 600 }}
              >
                {rule.title}
              </Typography>
              <Typography
                sx={{
                  mt: 1,
                  fontSize: "15px",
                  lineHeight: 1.55,
                  color: "ink.2",
                }}
              >
                {rule.text}
              </Typography>
            </Box>
          ))}
        </Box>
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

// Breaks at the @ when the column is narrower than the address, never mid-word.
function MailLink({ mail, sx }: { mail: string; sx?: object }) {
  const [user, domain] = mail.split("@");
  return (
    <Box component="a" href={`mailto:${mail}`} sx={{ ...mailLinkSx, ...sx }}>
      {user}@<wbr />
      {domain}
    </Box>
  );
}

// 12px above and below on phones: a 44px touch target.
const stepLinkSx = { display: "inline-block", py: { xs: 3, md: 1 } } as const;

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
              // Desktop: number, title and text side by side across the page.
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
                fontFamily: "'Source Serif 4', Georgia, serif",
                fontSize: { xs: "20px", md: "26px" },
                lineHeight: 1,
              }}
            >
              {i + 1}
            </Box>
            <Typography
              variant="h4"
              component="h3"
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
                    mt: { xs: 1, md: 3 },
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-start",
                  }}
                >
                  {step.links.map((l) =>
                    l.href.startsWith("mailto:") ? (
                      <MailLink
                        key={l.href}
                        mail={l.label}
                        sx={{ ...stepLinkSx, fontSize: "14px" }}
                      />
                    ) : (
                      <Link
                        key={l.href}
                        href={l.href}
                        style={{ ...inlineLinkStyle, fontSize: "15px" }}
                      >
                        <Box component="span" sx={stepLinkSx}>
                          {l.label}
                        </Box>
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
    <Box
      component="section"
      sx={{ px: { xs: 6, md: 14 }, pt: { xs: 10, md: 14 }, pb: 8 }}
    >
      <SectionHeading eyebrow="Löpande arbete" title="Sedan, år för år" />
      <Box
        component="ul"
        sx={{
          listStyle: "none",
          m: 0,
          p: 0,
          borderBottom: 1,
          borderColor: "line.main",
        }}
      >
        {YEARLY.map((item) => (
          <Box
            key={item.title}
            component="li"
            sx={{
              display: "grid",
              // 388px = the number and title columns of the steps above, so
              // the two text columns line up.
              gridTemplateColumns: { md: "minmax(0, 388px) minmax(0, 1fr)" },
              columnGap: 8,
              py: { xs: 5, md: 6 },
              borderTop: 1,
              borderColor: "line.main",
            }}
          >
            <Typography
              variant="h4"
              component="h3"
              sx={{ m: 0, fontSize: "22px" }}
            >
              {item.title}
            </Typography>
            <Typography
              sx={{
                mt: { xs: 2, md: 0.5 },
                maxWidth: "34rem",
                color: "ink.2",
                fontSize: "15px",
                lineHeight: 1.65,
              }}
            >
              {item.desc}
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
      id="kontakt"
      sx={{
        px: { xs: 6, md: 14 },
        pt: { xs: 10, md: 14 },
        pb: 20,
        // Clears the sticky site header when the intro button jumps here.
        scrollMarginTop: "72px",
      }}
    >
      <SectionHeading eyebrow="Kontakt" title="Hör av dig" />
      <Typography sx={{ mb: 6, maxWidth: "40rem", color: "ink.2" }}>
        Varje ras har en genbanksansvarig. Vem det är just nu står under{" "}
        <Link href="/styrelsen" style={inlineLinkStyle}>
          Styrelse och kontakt
        </Link>
        .
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))" },
          gap: { xs: 4, md: 6 },
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
            <MailLink mail={c.mail} sx={{ ...stepLinkSx, mt: 2 }} />
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
      <YearlySection />
      <ContactSection />
    </>
  );
}
