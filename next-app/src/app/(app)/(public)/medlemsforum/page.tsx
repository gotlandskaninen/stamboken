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
            ska få del av den. Är du inte medlem än är du välkommen att gå med.
            Avgiften är 200 kr om året och betalas till Plusgiro 35 03 44-8
            eller Swish 123 095 70 50. Kassören svarar på frågor om medlemskap
            via{" "}
            <Link href="mailto:info@gotlandskaninen.se" color="inherit">
              info@gotlandskaninen.se
            </Link>
            .
          </Typography>
          <Box sx={{ mt: 8, display: "flex", gap: 3, flexWrap: "wrap" }}>
            <LinkButton
              href="https://forum.gotlandskaninen.se"
              variant="contained"
            >
              Till forumet
            </LinkButton>
            <LinkButton href="/" variant="outlined">
              &larr; Till hem
            </LinkButton>
          </Box>
        </Box>
      </Box>
    </>
  );
}
