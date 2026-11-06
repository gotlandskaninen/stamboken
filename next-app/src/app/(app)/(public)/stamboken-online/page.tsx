import { Box, Typography } from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";
import { PageHeader } from "@/components/public/PageHeader";
import GoogleOneTap from "@/components/GoogleOneTap";
import { WipBanner } from "@/components/public/WipBanner.client";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Stamboken Online" };

export default function StambokenOnlinePage() {
  return (
    <>
      {/* App-entry page: surface Google One Tap so members can sign in fast. */}
      <GoogleOneTap />
      {/* Beta notice belongs to the Stamboken entry + app, not the association site. */}
      <WipBanner />
      <PageHeader
        section="Stamboken Online"
        title="Stamboken Online"
        lede="Föreningens digitala stamregister. Här samlas varje individ, kull och härstamning för gotlandskanin och mellerudskanin – alla kaniner som fått ett genbanksintyg."
        image={{
          src: "/stamboken/hero-ungar-tralada.jpg",
          alt: "Tre gotlandskaninungar i olika färger i en trälåda vid ladugårdsväggen",
          position: "50% 60%",
        }}
      />
      <Box component="section" sx={{ p: { xs: "40px 24px", md: "80px 56px" } }}>
        <Box
          sx={{
            bgcolor: "skog.soft",
            borderRadius: "8px",
            p: { xs: 6, md: 11 },
            maxWidth: 800,
          }}
        >
          <Typography variant="h2" sx={{ m: 0 }}>
            Stamboken Online
          </Typography>
          <Typography variant="lede" sx={{ mt: 4 }}>
            Stamboken Online är vårt digitala register för de två svenska
            lantraskaninerna. Uppfödarna lägger själva in sina individer, kullar
            och härstamningar, och varje kanin som får ett genbanksintyg
            utfärdat hamnar i föreningens centrala register – ett för
            gotlandskanin, ett för mellerudskanin. Uppfödare kan också göra en
            testparning i registret för att se hur nära släkt två tänkta
            avelsdjur är innan de paras.
          </Typography>
          <Box sx={{ mt: 8, display: "flex", gap: 3, flexWrap: "wrap" }}>
            <LinkButton href="/stamboken/min-besattning" variant="contained">
              Logga in i Stamboken
            </LinkButton>
            <LinkButton href="/foreningen" variant="outlined">
              Om föreningen
            </LinkButton>
          </Box>

          <Box
            sx={{
              mt: 10,
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 4,
              pt: 6,
              borderTop: "1px solid #c0ccb4",
            }}
          >
            {[
              { num: "900+", label: "Kaniner i registret" },
              { num: "200+", label: "Uppfödare" },
              { num: "2", label: "Lantraser" },
            ].map((s) => (
              <Box key={s.label} sx={{ textAlign: "center" }}>
                <Typography
                  sx={{
                    fontFamily: "'Source Serif 4', Georgia, serif",
                    fontSize: { xs: "28px", md: "48px" },
                    lineHeight: 1,
                    color: "skog.main",
                  }}
                >
                  {s.num}
                </Typography>
                <Typography
                  variant="mono"
                  sx={{
                    mt: 1.5,
                    fontSize: "11px",
                    textTransform: "uppercase",
                    letterSpacing: "0.12em",
                    display: "block",
                  }}
                >
                  {s.label}
                </Typography>
              </Box>
            ))}
          </Box>

          <Typography
            sx={{ mt: 6, fontSize: "15px", lineHeight: 1.65, color: "ink.2" }}
          >
            Med registret på plats går det att följa en kanins anor bakåt, hitta
            kullar och hålla ihop avelsarbetet mellan besättningar.
          </Typography>
          <Typography
            sx={{ mt: 4, fontSize: "15px", lineHeight: 1.65, color: "ink.2" }}
          >
            Du loggar in med ditt föreningskonto: en e-postadress på
            gotlandskaninen.se som föreningen skapar åt dig som medlem. Vi
            arbetar på att det ska gå att logga in med vanligt lösenord också.
            Frågor om konton och inloggning besvaras på
            admin@gotlandskaninen.se.
          </Typography>
        </Box>
      </Box>
    </>
  );
}
