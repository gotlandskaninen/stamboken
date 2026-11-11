import Image from "next/image";
import Link from "next/link";
import { Box, Typography } from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";
import { Icon, ICONS } from "@/components/public/Icons";
import { OrnamentDivider } from "@/components/public/OrnamentDivider";
import { EUFundingBadge } from "@/components/public/EUFundingBadge";

function HeroSection() {
  return (
    <Box component="section" sx={{ p: { xs: 3, md: 6 }, pb: 0 }}>
      <Box
        sx={{
          position: "relative",
          borderRadius: "14px",
          overflow: "hidden",
          minHeight: { sm: 480, md: 620 },
          // Phones: the tall stacked copy would crop the landscape photo down to
          // an eye, so the photo becomes a 3:2 banner and the text sits on a
          // skog panel below it. From sm the photo is the backdrop again (the
          // Snabbgenvägar card must stay above the fold on tablets).
          bgcolor: { xs: "skog.main", sm: "transparent" },
        }}
      >
        <Box
          sx={{
            position: { xs: "relative", sm: "absolute" },
            inset: { sm: 0 },
            aspectRatio: { xs: "3 / 2", sm: "auto" },
          }}
        >
          <Image
            src="/stamboken/hero-ungkanin-grass.jpg"
            alt="Ung sandfärgad gotlandskanin i gräset"
            fill
            priority
            sizes="100vw"
            style={{ objectFit: "cover", objectPosition: "60% 40%" }}
          />
          <Box
            sx={{
              position: "absolute",
              inset: 0,
              background: {
                xs: "linear-gradient(180deg, rgba(31,27,22,0) 70%, rgba(31,51,34,0.85) 100%)",
                sm: "linear-gradient(180deg, rgba(31,27,22,0.42) 0%, rgba(31,27,22,0.32) 48%, rgba(31,27,22,0.82) 100%)",
              },
            }}
          />
        </Box>

        <Box
          sx={{
            position: "relative",
            p: {
              xs: 5,
              sm: 6,
              md: "clamp(32px, 5vw, 64px) clamp(24px, 4vw, 56px) 56px",
            },
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              md: "minmax(0, 1.4fr) minmax(280px, 1fr)",
            },
            gap: { xs: 6, md: "clamp(24px, 4vw, 48px)" },
            alignItems: "end",
            minHeight: { sm: 480, md: 620 },
          }}
        >
          {/* Left — headline */}
          <Box>
            <Box
              sx={{
                mb: { xs: 5, md: 8 },
                display: "inline-flex",
                alignItems: "center",
                gap: 4.5,
                flexWrap: "wrap",
              }}
            >
              <Box
                sx={{
                  width: { xs: 64, md: 88 },
                  height: { xs: 64, md: 88 },
                  bgcolor: "paper.main",
                  borderRadius: "50%",
                  // The site header already shows the logo right above on phones.
                  display: { xs: "none", sm: "inline-flex" },
                  alignItems: "center",
                  justifyContent: "center",
                  boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
                  flexShrink: 0,
                  "& img": {
                    width: { xs: 54, md: 76 },
                    height: { xs: 54, md: 76 },
                  },
                }}
              >
                <Image
                  src="/stamboken/logo.png"
                  alt=""
                  width={76}
                  height={76}
                />
              </Box>
              <Box sx={{ color: "paper.main" }}>
                <Typography
                  variant="mono"
                  sx={{
                    color: "paper.main",
                    fontSize: "11px",
                    letterSpacing: "0.16em",
                    textTransform: "uppercase",
                    opacity: 0.9,
                  }}
                >
                  Föreningen sedan 1984
                </Typography>
                <Typography
                  sx={{
                    fontFamily: "'Source Serif 4', Georgia, serif",
                    fontStyle: "italic",
                    fontSize: "22px",
                    mt: 1,
                    color: "paper.main",
                  }}
                >
                  Bevarar svenska lantraskaniner
                </Typography>
              </Box>
            </Box>

            <Typography
              variant="h1"
              component="h1"
              sx={{
                m: 0,
                color: "paper.main",
                fontSize: "clamp(34px, 7vw, 84px)",
                lineHeight: 1,
                letterSpacing: "-0.025em",
              }}
            >
              Vi bevarar{" "}
              <Box
                component="span"
                sx={{
                  fontFamily: "'Source Serif 4', Georgia, serif",
                  fontStyle: "italic",
                }}
              >
                gotlandskanin
              </Box>{" "}
              och{" "}
              <Box
                component="span"
                sx={{
                  fontFamily: "'Source Serif 4', Georgia, serif",
                  fontStyle: "italic",
                }}
              >
                mellerudskanin
              </Box>{" "}
              – de sista resterna av Sveriges lantraskaniner.
            </Typography>
            <Typography
              sx={{
                mt: { xs: 4, md: 6 },
                color: "rgba(244,241,234,0.88)",
                maxWidth: 620,
                fontSize: "clamp(15px, 1.4vw, 19px)",
                lineHeight: 1.5,
              }}
            >
              Välkommen till Föreningen Gotlandskaninens officiella hemsida. Här
              skriver vi om våra lantraskaniner, om bevarandearbetet och om
              föreningens verksamhet.
            </Typography>
          </Box>

          {/* Right — quick shortcuts card */}
          <Box
            component="aside"
            sx={{
              bgcolor: "paper.main",
              borderRadius: "8px",
              p: 6.5,
              boxShadow: 3,
            }}
          >
            <Typography variant="eyebrow" sx={{ mb: 3.5, display: "block" }}>
              Snabbgenvägar
            </Typography>
            <Box sx={{ display: "grid", gap: 2.5 }}>
              <LinkButton
                href="/bli-medlem"
                variant="contained"
                fullWidth
                startIcon={<Icon d={ICONS.heart} size={15} />}
              >
                Bli medlem
              </LinkButton>
              <LinkButton
                href="/stamboken-online"
                variant="outlined"
                fullWidth
                startIcon={<Icon d={ICONS.book} size={15} />}
              >
                Stamboken Online
              </LinkButton>
              <LinkButton
                href="/medlemsforum"
                variant="outlined"
                fullWidth
                startIcon={<Icon d={ICONS.message} size={15} />}
              >
                Medlemsforum
              </LinkButton>
            </Box>
            <Box
              sx={{
                mt: 4.5,
                pt: 4,
                borderTop: 1,
                borderColor: "line.main",
                display: "flex",
                gap: 3.5,
                fontSize: "12px",
                flexWrap: "wrap",
              }}
            >
              <Box
                component="a"
                href="https://www.facebook.com/profile.php?id=100064726114664"
                target="_blank"
                rel="noopener noreferrer"
                sx={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 1.5,
                  textDecoration: "none",
                  color: "ink.2",
                  "&:hover": { color: "ink.main" },
                }}
              >
                <Box
                  sx={{
                    width: 22,
                    height: 22,
                    borderRadius: "4px",
                    bgcolor: "#1877F2",
                    color: "#fff",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                  }}
                >
                  f
                </Box>
                Facebooksida
              </Box>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

const PILLARS = [
  {
    title: "Bli medlem",
    desc: "Som medlem stödjer du bevarandet av två svenska lantraser. Du får tidskriften Koharen tre gånger om året och tillgång till medlemsforum.",
    href: "/bli-medlem",
    icon: ICONS.heart,
    tint: "lera",
  },
  {
    title: "Föreningen",
    desc: "Om vår verksamhet sedan 1984. Drygt 400 medlemmar över hela landet och ett genbankssystem för två lantraser.",
    href: "/foreningen",
    icon: ICONS.shield,
    tint: "skog",
  },
  {
    title: "Lantraskaninen",
    desc: "Vad är en lantraskanin? En översikt av begreppet, vad som skiljer dem från andra raser och varför de behöver bevaras.",
    href: "/lantraskaninen",
    icon: ICONS.leaf,
    tint: "mossa",
  },
];

function PillarsSection() {
  return (
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, pt: 16, pb: 8 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(80px, 160px) 1fr" },
          gap: 8,
          mb: 9,
        }}
      >
        <Typography variant="eyebrow">Föreningen</Typography>
        <Typography variant="h2" sx={{ m: 0 }}>
          Vad vi gör och hur du kan vara med i arbetet.
        </Typography>
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: 5,
        }}
      >
        {PILLARS.map((c) => (
          <Link
            key={c.title}
            href={c.href}
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <Box
              sx={{
                bgcolor: "background.paper",
                border: 1,
                borderColor: "line.main",
                borderRadius: "8px",
                p: 7,
                height: "100%",
                transition: "transform 200ms cubic-bezier(0.2, 0.7, 0.2, 1)",
                "&:hover": { transform: "translateY(-2px)" },
              }}
            >
              <Box
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  mb: 6,
                }}
              >
                <Box
                  sx={{
                    width: 48,
                    height: 48,
                    borderRadius: "50%",
                    bgcolor: `${c.tint}.soft`,
                    color: c.tint === "lera" ? "lera.main" : "skog.main",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Icon d={c.icon} size={22} />
                </Box>
              </Box>
              <Typography
                variant="h4"
                component="h3"
                sx={{ m: 0, fontSize: "24px" }}
              >
                {c.title}
              </Typography>
              <Typography
                sx={{
                  mt: 3,
                  color: "ink.2",
                  fontSize: "15px",
                  lineHeight: 1.55,
                }}
              >
                {c.desc}
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
                Läs mer &rarr;
              </Typography>
            </Box>
          </Link>
        ))}
      </Box>
    </Box>
  );
}

// Card images are AI-generated illustrations chosen by the owner (2026-09-11);
// the gotlandskanin one portrays Blomma, 107-014G.
// `pos` keeps the rabbit in frame when the 320 px card crops the wide image
// on phones.
const BREEDS = [
  {
    name: "Gotlandskanin",
    latin: "Återupptäckt 1976 genom ett upprop i tidskriften Kaninuppfödaren",
    status: "Utrotningshotad",
    n: "~200",
    nLabel: "genbanksbesättningar",
    desc: "En lokal variant av den gamla svenska lantraskaninen, bevarad på Gotland. Klassad som utrotningshotad svensk husdjursras av Jordbruksverket.",
    href: "/gotlandskanin",
    img: "/stamboken/breed-gotlandskanin.jpg",
    alt: "Gotlandskaninen Blomma, 107-014G",
    pos: "30% 50%",
  },
  {
    name: "Mellerudskanin",
    latin:
      "Uppmärksammad genom personliga kontakter 2001 i Mellerud i Dalsland",
    status: "Utrotningshotad",
    n: "~50",
    nLabel: "genbanksbesättningar",
    desc: "Ytterligare en gren av den gamla lantrasen, bevarad som egen ras. Även den klassad som utrotningshotad svensk husdjursras av Jordbruksverket.",
    href: "/mellerudskanin",
    img: "/stamboken/breed-mellerudskanin.jpg",
    alt: "Mellerudskanin",
    pos: "75% 50%",
  },
];

function BreedsSection() {
  return (
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, pt: 8, pb: 16 }}>
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
          <Typography variant="lede" sx={{ mt: 3.5, maxWidth: 720 }}>
            Jordbruksverket klassar båda raserna som utrotningshotade svenska
            husdjursraser. Föreningen samordnar avelsarbetet i ett
            genbankssystem.
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
        {BREEDS.map((b) => (
          <Link
            key={b.name}
            href={b.href}
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
              <Box
                sx={{
                  position: "relative",
                  width: "100%",
                  height: 320,
                }}
              >
                <Image
                  src={b.img}
                  alt={b.alt}
                  fill
                  style={{ objectFit: "cover", objectPosition: b.pos }}
                />
              </Box>
              <Box sx={{ p: 7 }}>
                <Box
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    gap: 3,
                    flexWrap: "wrap",
                  }}
                >
                  <Box>
                    <Typography variant="h3" sx={{ m: 0 }}>
                      {b.name}
                    </Typography>
                    <Typography variant="mono" sx={{ mt: 1 }}>
                      {b.latin}
                    </Typography>
                  </Box>
                  <Box
                    sx={{
                      fontFamily: "'IBM Plex Mono', monospace",
                      fontSize: "11px",
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      px: 2,
                      py: 1,
                      borderRadius: "4px",
                      bgcolor: "lera.soft",
                      color: "#8a3f1f",
                      border: "1px solid #e6c0ad",
                    }}
                  >
                    {b.status}
                  </Box>
                </Box>
                <Typography sx={{ mt: 3.5, color: "ink.2", lineHeight: 1.6 }}>
                  {b.desc}
                </Typography>
                <Box
                  sx={{
                    mt: 5.5,
                    pt: 4.5,
                    borderTop: 1,
                    borderColor: "line.main",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 3,
                  }}
                >
                  <Box>
                    <Box
                      component="span"
                      sx={{
                        fontFamily: "'Source Serif 4', Georgia, serif",
                        fontSize: "30px",
                        lineHeight: 1,
                        letterSpacing: "-0.02em",
                        color: "skog.main",
                      }}
                    >
                      {b.n}
                    </Box>
                    <Typography
                      variant="mono"
                      component="span"
                      sx={{ ml: 2.5 }}
                    >
                      {b.nLabel}
                    </Typography>
                  </Box>
                  <Typography
                    sx={{
                      fontSize: "14px",
                      color: "ink.main",
                      textDecoration: "underline",
                      textDecorationColor: "line.strong",
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
  ["Genbanks­besättningar", "Drift och underhåll"],
  ["Medlems­tidningen", "Koharen, 3 nr/år"],
  ["Trycksaker", "Faktablad, Färgatlas"],
  ["Genbanksintyg", "Officiella dokument"],
  ["Kurser & utbildningar", "För medlemmar"],
  ["Transport av djur", "Värdefulla individer"],
  ["Obduktioner", "Veterinär­medicinsk uppföljning"],
  ["Marknadsföring", "Spridning av kunskap"],
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
            // minmax(0, 1fr): a plain 1fr track is minmax(auto, 1fr), and the
            // auto-fit EU_ITEMS grid below reports a 3-column min-content width
            // (688px) that widened this column past a phone screen; the section
            // is overflow:hidden, so the right half was simply cut off.
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
            sx={{
              mt: 5.5,
              color: "rgba(244,241,234,0.86)",
              maxWidth: 720,
            }}
          >
            Stödet går till genbanksbesättningarna, medlemstidningen,
            trycksaker, genbanksintyg, marknadsföring, kurser, utbildningar,
            transport av värdefulla djur samt obduktioner.
          </Typography>
          <Box
            sx={{
              mt: 9,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: 3.5,
              maxWidth: 720,
            }}
          >
            {EU_ITEMS.map(([t, s], i) => (
              <Box
                key={i}
                sx={{
                  p: "14px 16px",
                  bgcolor: "rgba(244,241,234,0.08)",
                  borderLeft: "2px solid #e8c8a8",
                  borderRadius: "0 4px 4px 0",
                }}
              >
                <Typography
                  sx={{
                    fontSize: "14px",
                    fontWeight: 500,
                    color: "paper.main",
                  }}
                >
                  {t}
                </Typography>
                <Typography
                  sx={{
                    fontSize: "12px",
                    color: "rgba(244,241,234,0.65)",
                    mt: 0.5,
                  }}
                >
                  {s}
                </Typography>
              </Box>
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
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, pt: 20, pb: 8 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(80px, 160px) 1fr" },
          gap: 8,
          mb: 10,
        }}
      >
        <Typography variant="eyebrow">Medlems&shy;verksamhet</Typography>
        <Typography variant="h2" sx={{ m: 0 }}>
          En tidskrift, ett forum, en stambok.
        </Typography>
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
    </Box>
  );
}

function CTASection() {
  return (
    <Box component="section" sx={{ px: { xs: 6, md: 14 }, pt: 8, pb: 20 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "minmax(80px, 160px) 1fr" },
          gap: 8,
          mb: 10,
        }}
      >
        <Typography variant="eyebrow">Medlemskap</Typography>
        <Typography variant="h2" sx={{ m: 0 }}>
          Bli en del av bevarandet.
        </Typography>
      </Box>

      <Box
        sx={{
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
        <Box sx={{ minWidth: 280 }}>
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
            Som medlem får du föreningens medlemstidning Koharen tre gånger om
            året, tillgång till medlemsforum och Stamboken Online.
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
      <PillarsSection />
      <OrnamentDivider />
      <BreedsSection />
      <EUSection />
      <MemberSection />
      <CTASection />
    </>
  );
}
