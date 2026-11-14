import Link from "next/link";
import Image from "next/image";
import { Box, Typography } from "@mui/material";
import { EUFundingBadge } from "./EUFundingBadge";

type FooterLink = {
  label: string;
  href: string;
  external?: boolean;
};

const CONTACT_EMAIL = "info@gotlandskaninen.se";

const PAYMENT = [
  { label: "Plusgiro", value: "35 03 44-8" },
  { label: "Swish", value: "123 095 70 50" },
];

const FOOTER_ROWS: Array<{ heading: string; links: FooterLink[] }> = [
  {
    heading: "Läs mer",
    links: [
      { label: "Föreningen", href: "/foreningen" },
      { label: "Historik", href: "/historik" },
      { label: "Lantraskaninen", href: "/lantraskaninen" },
      { label: "Gotlandskanin", href: "/gotlandskanin" },
      { label: "Mellerudskanin", href: "/mellerudskanin" },
      { label: "Bli genbanksbesättning", href: "/bli-genbanksbesattning" },
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
    links: [{ label: "Styrelse / Kontakt", href: "/styrelsen" }],
  },
];

// 12px above and below on phones: a 44px touch target.
const footerLinkSx = {
  display: "inline-block",
  py: { xs: 3, md: 1 },
  color: "ink.2",
  fontSize: "14px",
  textDecoration: "underline",
  textDecorationColor: "var(--sb-line-strong)",
  textDecorationThickness: "1px",
  textUnderlineOffset: "3px",
  transition: "text-decoration-color 200ms",
  "&:hover": { textDecorationColor: "var(--sb-lera)" },
} as const;

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
      {/* Brand left; how to reach and pay the association right */}
      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", md: "row" },
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: { xs: 5, md: 12 },
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 3 }}>
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
                fontSize: "11px",
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
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            alignItems: { md: "flex-end" },
            gap: { md: 1.5 },
          }}
        >
          <Box component="a" href={`mailto:${CONTACT_EMAIL}`} sx={footerLinkSx}>
            {CONTACT_EMAIL}
          </Box>
          <Box
            component="dl"
            sx={{
              m: 0,
              display: "flex",
              flexDirection: { xs: "column", md: "row" },
              gap: { xs: 1.5, md: 7 },
            }}
          >
            {PAYMENT.map((row) => (
              <Box
                key={row.label}
                sx={{ display: "flex", alignItems: "baseline", columnGap: 4 }}
              >
                <Typography
                  component="dt"
                  sx={{ fontSize: "13px", color: "ink.2" }}
                >
                  {row.label}
                </Typography>
                <Typography
                  component="dd"
                  variant="mono"
                  sx={{
                    m: 0,
                    fontSize: "14px",
                    fontWeight: 500,
                    whiteSpace: "nowrap",
                    color: "ink.main",
                  }}
                >
                  {row.value}
                </Typography>
              </Box>
            ))}
          </Box>
        </Box>
      </Box>

      {/* One row per group: label left, links flowing right. Phones: the
          label on top and the links in two columns. */}
      <Box sx={{ mt: 8, borderTop: 1, borderColor: "line.main" }}>
        {FOOTER_ROWS.map((row) => (
          <Box
            key={row.heading}
            sx={{
              display: { md: "grid" },
              gridTemplateColumns: { md: "140px 1fr" },
              alignItems: "baseline",
              pt: { xs: 5, md: 3.5 },
              pb: { xs: 2, md: 3.5 },
              borderBottom: 1,
              borderColor: "line.main",
            }}
          >
            <Typography variant="eyebrow" sx={{ display: "block" }}>
              {row.heading}
            </Typography>
            <Box
              component="ul"
              sx={{
                listStyle: "none",
                p: 0,
                m: 0,
                mt: { xs: 1, md: 0 },
                display: { xs: "grid", md: "flex" },
                gridTemplateColumns: "1fr 1fr",
                flexWrap: "wrap",
                columnGap: { xs: 6, md: 7 },
              }}
            >
              {row.links.map((link) =>
                link.external ? (
                  <li key={link.href}>
                    <Box
                      component="a"
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      sx={footerLinkSx}
                    >
                      {link.label}
                    </Box>
                  </li>
                ) : (
                  <li key={link.href}>
                    <Link href={link.href} style={{ textDecoration: "none" }}>
                      <Box component="span" sx={footerLinkSx}>
                        {link.label}
                      </Box>
                    </Link>
                  </li>
                ),
              )}
            </Box>
          </Box>
        ))}
      </Box>

      {/* Bottom bar */}
      <Box
        sx={{
          pt: { xs: 6, md: 5 },
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
            alignItems: "center",
            fontSize: "12px",
            color: "ink.3",
            flexWrap: "wrap",
          }}
        >
          <span>&copy; 2026 Föreningen Gotlandskaninen</span>
          <Link href="/integritetspolicy" style={{ color: "inherit" }}>
            <Box
              component="span"
              sx={{
                display: "inline-block",
                py: { xs: 3, md: 0 },
                "@media (pointer: coarse)": { py: 3 },
              }}
            >
              Integritetspolicy
            </Box>
          </Link>
          <Box
            component="a"
            href="https://github.com/gotlandskaninen/stamboken"
            sx={{
              color: "inherit",
              display: "inline-block",
              py: { xs: 3, md: 0 },
            }}
          >
            Källkod (AGPL-3.0)
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
