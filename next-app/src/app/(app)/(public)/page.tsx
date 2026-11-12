import Image from "next/image";
import Link from "next/link";
import { Box, Typography } from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";
import { Icon, ICONS } from "@/components/public/Icons";
import { EUFundingBadge } from "@/components/public/EUFundingBadge";

const heroLinkSx = {
  display: "inline-block",
  py: 2,
  color: "ink.main",
  textDecoration: "underline",
  textDecorationColor: "var(--sb-line-strong)",
  textUnderlineOffset: "3px",
} as const;

const italicSx = {
  fontFamily: "'Source Serif 4', Georgia, serif",
  fontStyle: "italic",
} as const;

function HeroSection() {
  return (
    <Box
      component="section"
      className="landing-hero"
      sx={{
        px: { xs: 5, md: "clamp(24px, 5vw, 56px)" },
        pt: { xs: 3, md: 8.5 },
        display: "grid",
        gridTemplateColumns: {
          xs: "minmax(0, 1fr)",
          md: "minmax(0, 1.05fr) minmax(0, 1fr)",
        },
        gap: { xs: 4.5, md: "clamp(24px, 4vw, 64px)" },
        alignItems: "center",
      }}
    >
      <Box>
        <Typography
          variant="h1"
          component="h1"
          sx={{
            m: 0,
            fontSize: "clamp(34px, 4.4vw, 62px)",
            lineHeight: 1.05,
            letterSpacing: "-0.025em",
          }}
        >
          Vi bevarar{" "}
          <Box component="span" sx={italicSx}>
            gotlandskanin
          </Box>{" "}
          och{" "}
          <Box component="span" sx={italicSx}>
            mellerudskanin
          </Box>{" "}
          – de sista resterna av Sveriges lantraskaniner.
        </Typography>
        <Typography
          sx={{
            mt: 3.5,
            maxWidth: "46ch",
            fontSize: "clamp(17px, 1.5vw, 20px)",
            lineHeight: 1.5,
            color: "ink.2",
          }}
        >
          Raserna lever vidare hemma hos föreningens medlemmar. Som medlem är du
          med och håller dem vid liv.
        </Typography>
        <Box
          sx={{
            mt: 5,
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            columnGap: 5,
            rowGap: 3,
          }}
        >
          <LinkButton
            href="/bli-medlem"
            variant="contained"
            endIcon={<Icon d={ICONS.arrow} size={14} />}
            sx={{ flex: { xs: "1 1 100%", sm: "0 0 auto" } }}
          >
            Bli medlem
          </LinkButton>
          <Typography sx={{ fontSize: "15px", color: "ink.2" }}>
            200 kr om året, för hela familjen
          </Typography>
        </Box>
        <Typography
          sx={{
            mt: 5.5,
            pt: 3.5,
            borderTop: "1px solid var(--sb-line-strong)",
            maxWidth: "46ch",
            fontSize: "15px",
            color: "ink.2",
          }}
        >
          Omkring 400 medlemmar i hela landet håller i dag omkring 250
          genbanksbesättningar. Du behöver inte föda upp kaniner själv för att
          vara med.
        </Typography>
        <Box
          sx={{
            mt: 2,
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            columnGap: 3,
            fontSize: "15px",
            color: "ink.2",
          }}
        >
          <Box
            component="span"
            sx={{ flex: { xs: "1 1 100%", sm: "0 0 auto" } }}
          >
            Redan medlem?
          </Box>
          <Link href="/stamboken-online" style={{ textDecoration: "none" }}>
            <Box component="span" sx={heroLinkSx}>
              Stamboken Online
            </Box>
          </Link>
          <Link href="/medlemsforum" style={{ textDecoration: "none" }}>
            <Box component="span" sx={heroLinkSx}>
              Medlemsforum
            </Box>
          </Link>
        </Box>
      </Box>
      <Box
        sx={{
          position: "relative",
          order: { xs: -1, md: 0 },
          // Phones: a low banner, so "Bli medlem" stays on the first screen.
          aspectRatio: { xs: "2 / 1", md: "4 / 5" },
          maxHeight: { md: 640 },
          width: { xs: "auto", md: "100%" },
          mx: { xs: -2, md: 0 },
          borderRadius: "14px",
          overflow: "hidden",
          bgcolor: "paper.3",
        }}
      >
        <Image
          src="/stamboken/hero-ungkanin-grass.jpg"
          alt="Ung sandfärgad gotlandskanin i gräset"
          fill
          priority
          sizes="(min-width: 900px) 50vw, 100vw"
          style={{ objectFit: "cover", objectPosition: "58% 40%" }}
        />
      </Box>
    </Box>
  );
}

const MISSION_LINKS = [
  { href: "/foreningen", label: "Så fungerar genbanken" },
  { href: "/bli-genbank", label: "Bli genbanksbesättning" },
];

function MissionSection() {
  return (
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, pt: 16 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(80px, 160px) 1fr" },
          gap: 8,
        }}
      >
        <Typography variant="eyebrow">Uppdraget</Typography>
        <Box>
          <Typography variant="h2" sx={{ m: 0 }}>
            Genbanken finns hemma hos medlemmarna.
          </Typography>
          <Typography
            variant="lede"
            sx={{ mt: 3.5, maxWidth: 720, display: "block" }}
          >
            Den gamla svenska lantraskaninen var nära att försvinna när gårdarna
            slutade hålla kaniner och nya raser tog över. I dag lever den vidare
            hos uppfödare runt om i Sverige som har avtal med föreningen. Varje
            kanin i genbanken har ett intyg och finns i stamboken.
          </Typography>
          <Box sx={{ mt: 5, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {MISSION_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                style={{ color: "inherit", textDecoration: "none" }}
              >
                <Typography
                  component="span"
                  sx={{
                    color: "ink.main",
                    textDecoration: "underline",
                    textDecorationColor: "line.strong",
                    textUnderlineOffset: "3px",
                  }}
                >
                  {l.label} &rarr;
                </Typography>
              </Link>
            ))}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

// Card photos are members' photos, cropped to the card's 2:1. The
// mellerudskanin one is retouched: a fence behind the rabbit was removed.
const BREEDS = [
  {
    name: "Gotlandskanin",
    n: "200",
    desc: "En lokal variant av den gamla svenska lantraskaninen, bevarad på Gotland.",
    href: "/gotlandskanin",
    img: "/stamboken/breed-gotlandskanin.jpg",
    alt: "Brokig gotlandskanin på en äng",
    pos: "55% 50%",
  },
  {
    name: "Mellerudskanin",
    n: "50",
    desc: "Ytterligare en gren av den gamla lantrasen, bevarad som egen ras.",
    href: "/mellerudskanin",
    img: "/stamboken/breed-mellerudskanin.jpg",
    alt: "Mellerudskanin med svartvit holländarteckning i gräset",
    pos: "50% 50%",
  },
];

function BreedsSection() {
  return (
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, pt: 16, pb: 16 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(80px, 160px) 1fr" },
          gap: 8,
          mb: 10,
        }}
      >
        <Typography variant="eyebrow">Raserna</Typography>
        <Box>
          <Typography variant="h2" sx={{ m: 0 }}>
            Två kaninraser med ursprung i den svenska lantraskaninen.
          </Typography>
          <Typography
            variant="lede"
            sx={{ mt: 3.5, maxWidth: 720, display: "block" }}
          >
            Jordbruksverket klassar båda raserna som utrotningshotade svenska
            husdjursraser. Föreningen samordnar avelsarbetet i ett
            genbankssystem.
          </Typography>
        </Box>
      </Box>

      <Box
        className="breed-cards"
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "minmax(0, 1fr)",
            md: "repeat(2, minmax(0, 1fr))",
          },
          gap: 8,
        }}
      >
        {BREEDS.map((b) => (
          <Link
            key={b.name}
            href={b.href}
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <Box
              component="article"
              sx={{
                height: "100%",
                bgcolor: "background.paper",
                border: 1,
                borderColor: "line.main",
                borderRadius: "8px",
                overflow: "hidden",
                "& img": {
                  transition: "transform 360ms cubic-bezier(0.2, 0.7, 0.2, 1)",
                },
                "&:hover img": { transform: "scale(1.02)" },
                "@media (prefers-reduced-motion: reduce)": {
                  "& img": { transition: "none" },
                  "&:hover img": { transform: "none" },
                },
              }}
            >
              <Box
                sx={{
                  position: "relative",
                  aspectRatio: "2 / 1",
                  overflow: "hidden",
                  bgcolor: "paper.3",
                }}
              >
                <Image
                  src={b.img}
                  alt={b.alt}
                  fill
                  sizes="(min-width: 900px) 50vw, 100vw"
                  style={{ objectFit: "cover", objectPosition: b.pos }}
                />
              </Box>
              <Box
                sx={{ px: { xs: 6.5, md: 9 }, pt: 8, pb: { xs: 6.5, md: 9 } }}
              >
                <Typography variant="h3" sx={{ m: 0 }}>
                  {b.name}
                </Typography>
                <Typography sx={{ mt: 3, color: "ink.2" }}>{b.desc}</Typography>
                <Box
                  sx={{
                    mt: 6.5,
                    display: "flex",
                    flexWrap: "wrap",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    columnGap: 4,
                    rowGap: 2,
                  }}
                >
                  <Typography sx={{ fontSize: "15px", color: "ink.2" }}>
                    Omkring {b.n} genbanksbesättningar
                  </Typography>
                  <Typography
                    sx={{
                      fontSize: "15px",
                      whiteSpace: "nowrap",
                      color: "ink.main",
                      textDecoration: "underline",
                      textDecorationColor: "var(--sb-line-strong)",
                      textUnderlineOffset: "3px",
                    }}
                  >
                    Läs mer &rarr;
                  </Typography>
                </Box>
              </Box>
            </Box>
          </Link>
        ))}
      </Box>
    </Box>
  );
}

const EU_ITEMS = [
  "Genbanksbesättningarna",
  "Medlemstidningen Koharen",
  "Trycksaker som faktablad och färgatlas",
  "Genbanksintyg",
  "Kurser och utbildningar",
  "Transport av värdefulla djur",
  "Obduktioner",
  "Marknadsföring",
];

function EUSection() {
  return (
    <Box
      component="section"
      id="eu-stod"
      sx={{
        position: "relative",
        color: "paper.main",
        py: 20,
        px: { xs: 6, md: 14 },
        overflow: "hidden",
      }}
    >
      <Image
        src="/stamboken/eu-landscape-fence-barn.jpg"
        alt=""
        fill
        style={{
          objectFit: "cover",
          objectPosition: "center 60%",
          opacity: 0.45,
        }}
        aria-hidden="true"
      />
      <Box
        sx={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(180deg, rgba(31,51,34,0.86) 0%, rgba(47,74,50,0.94) 100%)",
        }}
      />
      <Box
        sx={{
          position: "relative",
          display: "grid",
          gridTemplateColumns: {
            xs: "minmax(0, 1fr)",
            md: "minmax(80px, 160px) minmax(0, 1fr) minmax(220px, 280px)",
          },
          gap: 10,
          alignItems: "start",
        }}
      >
        <Typography variant="eyebrow" sx={{ color: "rgba(244,241,234,0.78)" }}>
          EU-stöd
        </Typography>
        <Box>
          <Typography
            variant="h2"
            sx={{ m: 0, color: "paper.main", maxWidth: 720 }}
          >
            Föreningen Gotlandskaninen får stöd från{" "}
            <Box
              component="span"
              sx={{
                color: "#e8c8a8",
              }}
            >
              EU
            </Box>{" "}
            för att bevara gotlands- och mellerudskanin.
          </Typography>
          <Typography
            variant="lede"
            sx={{ mt: 5.5, display: "block", color: "rgba(244,241,234,0.86)" }}
          >
            Stödet går till:
          </Typography>
          <Box
            component="ul"
            sx={{
              mt: 4.5,
              mb: 0,
              pl: 5,
              "& li::marker": { color: "#e8c8a8" },
              display: "grid",
              gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
              columnGap: 8,
              rowGap: 3,
              maxWidth: 720,
            }}
          >
            {EU_ITEMS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </Box>
        </Box>
        <Box
          component="aside"
          sx={{
            display: "flex",
            flexDirection: "column",
            gap: 4.5,
            alignItems: "flex-start",
          }}
        >
          {/* Official EU funding lockup (emblem + mandated wording), on a
              white card so it stays compliant and legible over the dark strip. */}
          <EUFundingBadge orientation="vertical" height={132} />
        </Box>
      </Box>
    </Box>
  );
}

function MemberSection() {
  return (
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, py: 20 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(80px, 160px) 1fr" },
          gap: 8,
          mb: 10,
        }}
      >
        <Typography variant="eyebrow">Medlemskap</Typography>
        <Box>
          <Typography variant="h2" sx={{ m: 0 }}>
            Bli en del av bevarandet.
          </Typography>
          <Typography
            variant="lede"
            sx={{ mt: 3.5, maxWidth: 720, display: "block" }}
          >
            Som medlem får du en tidskrift, ett forum och en stambok. Och du är
            med och håller raserna vid liv, oavsett om du föder upp kaniner
            själv.
          </Typography>
        </Box>
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            md: "repeat(auto-fit, minmax(380px, 1fr))",
          },
          gap: 6,
        }}
      >
        {[
          {
            href: "/medlemsforum",
            img: "/stamboken/koharen-kit-in-hands.jpg",
            badge: "Koharen / Medlemsforum",
            badgeColor: "lera" as const,
            title: "Tidskriften sedan 1984 och forumet på nätet.",
            desc: "Som medlem får du Koharen tre gånger om året. I tidningen finns information till medlemmarna, artiklar och reportage, annonser samt kontaktuppgifter.",
            cta: "Öppna medlemsforum →",
          },
          {
            href: "/stamboken-online",
            img: "/stamboken/breeding-notebook.jpg",
            badge: "Stamboken Online",
            badgeColor: "skog" as const,
            title: "Den digitala stamboken för medlemmar.",
            desc: "Registrera individer, kullar och härstamning. Varje kanin som fått genbanksintyg finns i föreningens centrala register.",
            cta: "Logga in →",
          },
        ].map((card) => (
          <Link
            key={card.href}
            href={card.href}
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <Box
              component="article"
              sx={{
                bgcolor: "background.paper",
                border: 1,
                borderColor: "line.main",
                borderRadius: "8px",
                overflow: "hidden",
                transition: "transform 200ms cubic-bezier(0.2, 0.7, 0.2, 1)",
                "&:hover": { transform: "translateY(-2px)" },
              }}
            >
              <Box sx={{ position: "relative", width: "100%", height: 280 }}>
                <Image
                  src={card.img}
                  alt=""
                  fill
                  style={{ objectFit: "cover" }}
                />
              </Box>
              <Box sx={{ p: 7 }}>
                <Box
                  sx={{
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: "11px",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    px: 2,
                    py: 1,
                    borderRadius: "4px",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 1.5,
                    bgcolor:
                      card.badgeColor === "lera" ? "lera.soft" : "skog.soft",
                    color: card.badgeColor === "lera" ? "#8a3f1f" : "skog.main",
                    border: "1px solid",
                    borderColor:
                      card.badgeColor === "lera" ? "#e6c0ad" : "#c0ccb4",
                  }}
                >
                  {card.badge}
                </Box>
                <Typography
                  variant="h4"
                  component="h3"
                  sx={{ mt: 3.5, m: "14px 0 0", fontSize: "26px" }}
                >
                  {card.title}
                </Typography>
                <Typography
                  sx={{
                    mt: 3,
                    color: "ink.2",
                    lineHeight: 1.6,
                    fontSize: "15px",
                  }}
                >
                  {card.desc}
                </Typography>
                <Typography
                  sx={{
                    mt: 4.5,
                    fontSize: "14px",
                    color: "ink.main",
                    textDecoration: "underline",
                    textDecorationColor: "line.strong",
                    textUnderlineOffset: "3px",
                  }}
                >
                  {card.cta}
                </Typography>
              </Box>
            </Box>
          </Link>
        ))}
      </Box>

      <Box
        sx={{
          mt: 6,
          bgcolor: "paper.2",
          border: 1,
          borderColor: "line.strong",
          borderRadius: "8px",
          p: { xs: 6, md: 11 },
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "64px 1fr auto" },
          gap: 6,
          alignItems: "center",
        }}
      >
        <Box
          sx={{
            width: 64,
            height: 64,
            bgcolor: "paper.main",
            borderRadius: "50%",
            display: { xs: "none", md: "inline-flex" },
            alignItems: "center",
            justifyContent: "center",
            boxShadow: 1,
          }}
        >
          <Image src="/stamboken/logo.png" alt="" width={56} height={56} />
        </Box>
        <Box>
          <Typography variant="h3" sx={{ m: 0 }}>
            200 kr om året.
          </Typography>
          <Typography
            sx={{
              mt: 2,
              color: "ink.2",
              lineHeight: 1.55,
              maxWidth: 600,
            }}
          >
            Medlemskapet gäller hela familjen.
          </Typography>
        </Box>
        <Box sx={{ display: "flex", gap: 2.5, flexWrap: "wrap" }}>
          <LinkButton
            href="/bli-medlem"
            variant="contained"
            endIcon={<Icon d={ICONS.arrow} size={14} />}
          >
            Bli medlem
          </LinkButton>
          <LinkButton href="/foreningen" variant="text">
            Om föreningen
          </LinkButton>
        </Box>
      </Box>
    </Box>
  );
}

export default function HomePage() {
  return (
    <>
      <HeroSection />
      <MissionSection />
      <BreedsSection />
      <EUSection />
      <MemberSection />
    </>
  );
}
