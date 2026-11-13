import { Box, Link, Typography } from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";
import { PageHeader } from "@/components/public/PageHeader";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Medlemsforum" };

export default function MedlemsforumPage() {
  return (
    <>
      <PageHeader
        section="Medlemsforum"
        title="Medlemsforum"
        lede="En sluten mötesplats för dig som är medlem. Här pratar vi avel, jämför erfarenheter från egna kullar och håller kontakten med andra som föder upp gotlands- och mellerudskaniner."
        image={{
          src: "/stamboken/hero-kustvandring.jpg",
          alt: "Medlemmar på vandring längs kusten under föreningens utflykt",
          position: "50% 55%",
        }}
      />
      <Box component="section" sx={{ p: { xs: "40px 24px", md: "80px 56px" } }}>
        <Box sx={{ maxWidth: 620 }}>
          <Box sx={{ mb: 8 }}>
            <LinkButton
              href="https://forum.gotlandskaninen.se"
              variant="contained"
            >
              Till forumet
            </LinkButton>
            <Typography
              sx={{
                mt: 3,
                maxWidth: "36rem",
                fontSize: "15px",
                lineHeight: 1.65,
                color: "ink.2",
              }}
            >
              Forumet är en egen webbplats, forum.gotlandskaninen.se. Du loggar
              in med ditt föreningskonto: en e-postadress på gotlandskaninen.se
              som föreningen skapar åt dig som medlem. Frågor om konton och
              inloggning besvaras på{" "}
              <Link
                href="mailto:admin@gotlandskaninen.se"
                color="inherit"
                sx={{
                  "@media (pointer: coarse)": {
                    display: "inline-block",
                    minHeight: 44,
                    lineHeight: "44px",
                  },
                }}
              >
                admin@gotlandskaninen.se
              </Link>
              .
            </Typography>
          </Box>
          <Typography variant="h2" sx={{ m: 0, mb: 4 }}>
            Här ses vi mellan numren av Koharen
          </Typography>
          <Typography
            sx={{ fontSize: "17px", lineHeight: 1.65, color: "ink.2" }}
          >
            Mellan tidningsutskicken och årsmötena behöver vi ett ställe att
            prata på. Det är vad forumet är till för – en sluten mötesplats för
            dig som är registrerad medlem. Här ställer du frågor om avel, jämför
            hur dina kullar utvecklats och får råd av andra uppfödare som hållit
            på länge.
          </Typography>
          <Typography
            sx={{ mt: 4, fontSize: "17px", lineHeight: 1.65, color: "ink.2" }}
          >
            Mycket i avelsarbetet sitter i det praktiska: vilka parningar som
            fungerar, hur en kull utvecklas, vad du ska titta efter. Den
            kunskapen finns hos medlemmarna, och forumet är till för att fler
            ska få del av den. Är du inte medlem än är du välkommen att gå med:{" "}
            <Link href="/bli-medlem" color="inherit">
              så blir du medlem
            </Link>
            . Kassören svarar på frågor om medlemskap via{" "}
            <Link href="mailto:info@gotlandskaninen.se" color="inherit">
              info@gotlandskaninen.se
            </Link>
            .
          </Typography>
        </Box>
      </Box>
    </>
  );
}
