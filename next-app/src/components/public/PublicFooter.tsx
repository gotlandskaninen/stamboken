import Link from "next/link";
import Image from "next/image";
import { Box, Typography } from "@mui/material";
import { EUFundingBadge } from "./EUFundingBadge";

type FooterLink = {
  label: string;
  href: string;
  external?: boolean;
};

const FOOTER_COLUMNS: Array<{
  heading: string;
  links: FooterLink[];
  plusgiro?: { label: string; value: string };
}> = [
  {
    heading: "Läs mer",
    links: [
      { label: "Föreningen", href: "/foreningen" },
      { label: "Historik", href: "/historik" },
      { label: "Lantraskaninen", href: "/lantraskaninen" },
      { label: "Gotlandskanin", href: "/gotlandskanin" },
      { label: "Mellerudskanin", href: "/mellerudskanin" },
      { label: "Bli genbank", href: "/bli-genbank" },
    ],
  },
  {
    heading: "Medlem",
    links: [
      { label: "Bli medlem", href: "/bli-medlem" },
      { label: "Medlemsforum", href: "/medlemsforum" },
      { label: "Stamboken Online", href: "/stamboken-online" },
      {
        label: "Facebooksida",
        href: "https://www.facebook.com/profile.php?id=100064726114664",
        external: true,
      },
    ],
  },
  {
    heading: "Kontakt",
    links: [
      {
        label: "info@gotlandskaninen.se",
        href: "mailto:info@gotlandskaninen.se",
      },
      { label: "Styrelse / Kontakt", href: "/styrelsen" },
    ],
    plusgiro: { label: "Plusgiro", value: "35 03 44-8" },
  },
];

export function PublicFooter() {
  return (
    <Box
      component="footer"
      sx={{
        bgcolor: "background.paper",
        borderTop: 1,
        borderColor: "line.main",
        pt: 14,
        pb: 7,
        px: { xs: 6, md: 10 },
      }}
    >
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            sm: "1fr 1fr",
            md: "2fr 1fr 1fr 1fr",
          },
          gap: 12,
          mb: 12,
        }}
      >
        {/* Brand column */}
        <Box>
          <Box sx={{ display: "flex", alignItems: "center", gap: 3, mb: 4.5 }}>
            <Image src="/stamboken/logo.png" alt="" width={36} height={36} />
            <Box sx={{ lineHeight: 1 }}>
              <Typography
                sx={{
                  fontFamily: "'Source Serif 4', Georgia, serif",
                  fontSize: "17px",
                  fontWeight: 500,
                }}
              >
                Föreningen Gotlandskaninen
              </Typography>
              <Typography
                variant="mono"
                sx={{
                  fontSize: "10px",
                  letterSpacing: "0.14em",
                  textTransform: "uppercase",
                  color: "ink.3",
                  mt: 1,
                }}
              >
                Sedan 1984
              </Typography>
            </Box>
          </Box>
          <Typography
            sx={{
              maxWidth: 320,
              lineHeight: 1.55,
              color: "ink.2",
              fontSize: "14px",
            }}
          >
            En ideell förening som sedan 1984 bevarar två svenska lantraser av
            kanin – gotlandskanin och mellerudskanin – genom genbank, stambok
            och aktivt avelsarbete.
          </Typography>
        </Box>

        {/* Link columns */}
        {FOOTER_COLUMNS.map((col) => (
          <Box key={col.heading}>
            <Typography variant="eyebrow" sx={{ mb: 3, display: "block" }}>
              {col.heading}
            </Typography>
            <Box
              component="ul"
              sx={{
                listStyle: "none",
                p: 0,
                m: 0,
                display: "grid",
                gap: 2,
              }}
            >
              {col.links.map((link) =>
                link.href.startsWith("mailto:") || link.external ? (
                  <li key={link.href}>
                    <Box
                      component="a"
                      href={link.href}
                      {...(link.external
                        ? { target: "_blank", rel: "noopener noreferrer" }
                        : {})}
                      sx={{
                        color: "ink.main",
                        textDecoration: "underline",
                        textDecorationColor: "line.strong",
                        textUnderlineOffset: "3px",
                        textDecorationThickness: "1px",
                        fontSize: "14px",
                        transition: "text-decoration-color 200ms",
                        "&:hover": { textDecorationColor: "lera.main" },
                      }}
                    >
                      {link.label}
                    </Box>
                  </li>
                ) : (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      style={{
                        color: "#3D362C",
                        textDecoration: "underline",
                        textUnderlineOffset: "3px",
                        fontSize: "14px",
                      }}
                    >
                      {link.label}
                    </Link>
                  </li>
                ),
              )}
            </Box>
            {col.plusgiro && (
              <Box
                sx={{
                  mt: 4.5,
                  px: 3,
                  py: 2.5,
                  bgcolor: "paper.2",
                  border: 1,
                  borderColor: "line.main",
                  borderRadius: "8px",
                  maxWidth: 180,
                }}
              >
                <Typography
                  variant="mono"
                  sx={{
                    fontSize: "10px",
                    letterSpacing: "0.14em",
                    textTransform: "uppercase",
                    // ink.3 on paper.2 is 4.31:1; AA needs 4.5 for small text.
                    color: "ink.2",
                    display: "block",
                  }}
                >
                  {col.plusgiro.label}
                </Typography>
                <Typography
                  variant="mono"
                  sx={{
                    fontSize: "14px",
                    fontWeight: 500,
                    mt: 0.5,
                    color: "ink.main",
                  }}
                >
                  {col.plusgiro.value}
                </Typography>
              </Box>
            )}
          </Box>
        ))}
      </Box>

      {/* Bottom bar */}
      <Box
        sx={{
          borderTop: 1,
          borderColor: "line.main",
          pt: 6,
          display: "flex",
          gap: { xs: 4, md: 5 },
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <EUFundingBadge orientation="horizontal" />
        <Box
          sx={{
            display: "flex",
            gap: 5,
            fontSize: "12px",
            color: "ink.3",
            flexWrap: "wrap",
          }}
        >
          <span>&copy; 2026 Föreningen Gotlandskaninen</span>
          <Box
            component="a"
            href="https://github.com/gotlandskaninen/stamboken"
            sx={{ color: "inherit" }}
          >
            Källkod (AGPL-3.0)
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
