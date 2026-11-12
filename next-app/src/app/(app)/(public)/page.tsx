import Image from "next/image";
import Link from "next/link";
import { Box, Typography } from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";
import { Icon, ICONS } from "@/components/public/Icons";
import { EUFundingBadge } from "@/components/public/EUFundingBadge";

const heroLinkSx = {
  display: "inline-block",
  // 12px above and below: a 44px touch target on phones.
  py: 3,
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
          <Box sx={{ mt: 2, display: "flex", flexWrap: "wrap", columnGap: 6 }}>
            {MISSION_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                style={{ color: "inherit", textDecoration: "none" }}
              >
                <Box component="span" sx={heroLinkSx}>
                  {l.label} &rarr;
                </Box>
              </Link>
            ))}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

// Card photos are members' photos, cropped to the card's 3:2, and both are
// retouched. Gotlandskanin: the background behind the rabbit (a house, a
// fence) is replaced, and the photo is mirrored so the two rabbits face each
// other. Mellerudskanin: a fence behind the rabbit is removed.
const BREEDS = [
  {
    name: "Gotlandskanin",
    n: "200",
    desc: "En lokal variant av den gamla svenska lantraskaninen, bevarad på Gotland.",
    href: "/gotlandskanin",
    img: "/stamboken/breed-gotlandskanin.jpg",
    alt: "Vuxen gulbrokig gotlandskanin i gräset",
    pos: "45% 50%",
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
                  // 3:2, not wider: a sitting rabbit with its ears up is tall.
                  aspectRatio: "3 / 2",
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

function EUSection() {
  return (
    <Box
      component="section"
      id="eu-stod"
      className="eu-section"
      sx={{
        bgcolor: "skog.main",
        color: "paper.main",
        py: 9,
        px: { xs: 6, md: "clamp(24px, 4vw, 56px)" },
      }}
    >
      <Box
        sx={{
          maxWidth: 1100,
          mx: "auto",
          display: "flex",
          flexDirection: { xs: "column", md: "row" },
          alignItems: { xs: "flex-start", md: "center" },
          gap: { xs: 5, md: 8 },
        }}
      >
        {/* Official EU funding lockup (emblem + mandated wording), on a
            white card so it stays compliant and legible over the dark strip. */}
        <Box sx={{ flex: "none", lineHeight: 0 }}>
          <EUFundingBadge orientation="vertical" height={104} />
        </Box>
        <Box sx={{ maxWidth: "72ch", color: "rgba(244,241,234,0.92)" }}>
          {/* A heading for the section outline, set as the first sentence. */}
          <Typography
            component="h2"
            sx={{ display: "inline", fontWeight: 600, color: "paper.main" }}
          >
            Föreningen Gotlandskaninen får stöd från EU för att bevara gotlands-
            och mellerudskanin.
          </Typography>{" "}
          <Typography component="span">
            Stödet går till genbanksbesättningarna, medlemstidningen Koharen,
            trycksaker, genbanksintyg, kurser och utbildningar, transport av
            värdefulla djur, obduktioner och marknadsföring.
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}

const MEMBER_BENEFITS: {
  title: string;
  text: string;
  href?: string;
  cta?: string;
}[] = [
  {
    title: "Tidskriften Koharen",
    text: "Tre nummer om året med artiklar, reportage, annonser och kontaktuppgifter.",
  },
  {
    title: "Medlemsforum",
    text: "Fråga och jämför med andra uppfödare.",
    href: "/medlemsforum",
    cta: "Till forumet",
  },
  {
    title: "Stamboken Online",
    text: "Registrera kaniner, kullar och härstamning.",
    href: "/stamboken-online",
    cta: "Till Stamboken",
  },
];

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
        className="member-body"
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "minmax(0, 1fr)",
            md: "minmax(0, 0.95fr) minmax(0, 1fr)",
          },
          gap: { xs: 6, md: 12 },
          alignItems: "center",
        }}
      >
        <Box
          sx={{
            position: "relative",
            aspectRatio: { xs: "3 / 2", md: "4 / 3" },
            borderRadius: "8px",
            overflow: "hidden",
            bgcolor: "paper.3",
          }}
        >
          <Image
            src="/stamboken/medlem-angsbild.jpg"
            alt="Ung brokig gotlandskanin på en äng"
            fill
            sizes="(min-width: 900px) 45vw, 100vw"
            style={{ objectFit: "cover", objectPosition: "60% 50%" }}
          />
        </Box>
        <Box>
          <Box component="ul" sx={{ m: 0, p: 0, listStyle: "none" }}>
            {MEMBER_BENEFITS.map((b, i) => (
              <Box
                component="li"
                key={b.title}
                sx={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) auto",
                  columnGap: 6,
                  alignItems: "center",
                  py: 4.5,
                  borderTop: "1px solid var(--sb-line)",
                  borderBottom:
                    i === MEMBER_BENEFITS.length - 1
                      ? "1px solid var(--sb-line)"
                      : "none",
                }}
              >
                <Box>
                  <Typography
                    component="h3"
                    sx={{ m: 0, fontSize: "17px", fontWeight: 600 }}
                  >
                    {b.title}
                  </Typography>
                  <Typography sx={{ mt: 1, maxWidth: "46ch", color: "ink.2" }}>
                    {b.text}
                  </Typography>
                </Box>
                {b.href && (
                  <Link href={b.href} style={{ textDecoration: "none" }}>
                    <Box
                      component="span"
                      sx={{
                        ...heroLinkSx,
                        fontSize: "15px",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {b.cta} &rarr;
                    </Box>
                  </Link>
                )}
              </Box>
            ))}
          </Box>
          <Box
            sx={{
              mt: 7,
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "space-between",
              alignItems: "center",
              columnGap: 6,
              rowGap: 4,
            }}
          >
            <Box>
              <Typography variant="h3" component="p" sx={{ m: 0 }}>
                200 kr om året
              </Typography>
              <Typography sx={{ mt: 1.5, fontSize: "15px", color: "ink.2" }}>
                Medlemskapet gäller hela familjen.
              </Typography>
            </Box>
            <LinkButton
              href="/bli-medlem"
              variant="contained"
              endIcon={<Icon d={ICONS.arrow} size={14} />}
              sx={{ flex: { xs: "1 1 100%", sm: "0 0 auto" } }}
            >
              Bli medlem
            </LinkButton>
          </Box>
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
      <MemberSection />
      <EUSection />
    </>
  );
}
