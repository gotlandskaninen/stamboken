import React from "react";
import { Box, Typography } from "@mui/material";

import SignInComponent from "@/components/auth/SignIn";
import { EUFundingBadge } from "@/components/public/EUFundingBadge";

const FONT_DISPLAY =
  "var(--font-source-serif), 'Source Serif 4', Georgia, serif";
const FONT_BODY = "var(--font-ibm-plex-sans), 'IBM Plex Sans', sans-serif";
const FONT_MONO = "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace";

function Brand({ light }: { light?: boolean }) {
  return (
    <Box sx={{ display: "inline-flex", alignItems: "center", gap: "14px" }}>
      <Box
        sx={{
          width: 56,
          height: 56,
          flex: "0 0 56px",
          borderRadius: "50%",
          bgcolor: "#FFFFFF",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: light ? "0 8px 24px rgba(0,0,0,0.28)" : "none",
          border: light ? "none" : "1px solid",
          borderColor: "line.main",
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/stamboken/logo.png"
          alt=""
          width={50}
          height={50}
          style={{ display: "block" }}
        />
      </Box>
      <Box>
        <Box
          sx={{
            fontFamily: FONT_DISPLAY,
            fontSize: 19,
            fontWeight: 500,
            letterSpacing: "-0.01em",
            lineHeight: 1.1,
            color: light ? "rgba(244,241,234,0.96)" : "ink.main",
          }}
        >
          Stamboken
        </Box>
        <Box
          sx={{
            fontFamily: FONT_MONO,
            fontSize: 10.5,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            mt: "4px",
            color: light ? "rgba(244,241,234,0.66)" : "ink.3",
          }}
        >
          Föreningen Gotlandskaninen
        </Box>
      </Box>
    </Box>
  );
}

export const metadata = { title: "Logga in" };

export default function SignInPage() {
  return (
    <Box
      sx={{
        minHeight: "100dvh",
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: "1.05fr 0.95fr" },
      }}
    >
      {/* LEFT — editorial image panel (desktop only) */}
      <Box
        component="aside"
        sx={{
          position: "relative",
          overflow: "hidden",
          display: { xs: "none", md: "flex" },
          flexDirection: "column",
          justifyContent: "space-between",
          p: "40px 48px",
          color: "paper.main",
          bgcolor: "skog.deep",
          // AI-generated illustration (owner-approved, 2026-09-11), used as
          // decorative panel art only. Not a photo of a real individual, so
          // it stays out of the CMS media library.
          backgroundImage: "url('/stamboken/signin-rabbit-meadow.jpg')",
          backgroundSize: "cover",
          // The tall panel shows roughly half of the 3:2 frame. The rabbit
          // fills the left half, so anchor left on wide screens (head ends up
          // right of the headline) and nudge in on narrower desktops so the
          // head is not cropped.
          backgroundPosition: { md: "35% 50%", lg: "0% 50%" },
        }}
      >
        <Box
          sx={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(165deg, rgba(31,51,34,0.42) 0%, rgba(31,51,34,0.30) 38%, rgba(20,32,22,0.86) 100%)",
          }}
        />

        <Box sx={{ position: "relative", zIndex: 1 }}>
          <Brand light />
        </Box>

        <Box sx={{ position: "relative", zIndex: 1, maxWidth: 460 }}>
          <Box
            sx={{
              fontFamily: FONT_MONO,
              fontSize: 12,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "rgba(244,241,234,0.72)",
              mb: "18px",
            }}
          >
            Genbank sedan 1984
          </Box>
          <Typography
            component="h1"
            sx={{
              fontFamily: FONT_DISPLAY,
              fontWeight: 400,
              fontSize: "clamp(30px, 2.6vw, 42px)",
              lineHeight: 1.05,
              letterSpacing: "-0.02em",
              m: 0,
            }}
          >
            Sveriges digitala stambok för{" "}
            <Box component="em" sx={{ fontStyle: "italic" }}>
              lantraskaniner
            </Box>
            .
          </Typography>
          <Typography
            sx={{
              fontFamily: FONT_BODY,
              fontSize: 16,
              lineHeight: 1.55,
              color: "rgba(244,241,234,0.82)",
              mt: "20px",
              maxWidth: 420,
            }}
          >
            Registrera kullar, följ stamtavlor och bevara genbanken för
            gotlandskanin och mellerudskanin — på ett ställe.
          </Typography>
        </Box>

        <Box sx={{ position: "relative", zIndex: 1 }}>
          <EUFundingBadge orientation="horizontal" height={44} />
        </Box>
      </Box>

      {/* RIGHT — form panel */}
      <Box
        component="main"
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          p: { xs: "40px 24px", md: "48px 32px" },
          bgcolor: "paper.main",
        }}
      >
        <Box sx={{ width: "100%", maxWidth: 380 }}>
          {/* mobile brand */}
          <Box sx={{ display: { xs: "block", md: "none" }, mb: "36px" }}>
            <Brand />
          </Box>

          <Box
            sx={{
              fontFamily: FONT_MONO,
              fontSize: 12,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "ink.3",
              mb: "12px",
            }}
          >
            Stamboken Online
          </Box>
          <Typography
            component="h2"
            sx={{
              fontFamily: FONT_DISPLAY,
              fontWeight: 400,
              fontSize: 40,
              lineHeight: 1.05,
              letterSpacing: "-0.02em",
              color: "ink.main",
              m: 0,
            }}
          >
            Logga in
          </Typography>
          <Typography
            sx={{
              fontFamily: FONT_BODY,
              fontSize: 15,
              color: "ink.2",
              mt: "10px",
              lineHeight: 1.5,
            }}
          >
            Välkommen tillbaka. Logga in för att komma åt stamboken.
          </Typography>

          <SignInComponent />

          {/* EU attribution on mobile (left panel is hidden) */}
          <Box
            sx={{
              display: { xs: "flex", md: "none" },
              justifyContent: "center",
              mt: "32px",
            }}
          >
            <EUFundingBadge orientation="horizontal" height={44} />
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
