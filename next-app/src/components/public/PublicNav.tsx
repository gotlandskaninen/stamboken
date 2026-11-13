import Link from "next/link";
import Image from "next/image";
import { Box, Typography } from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";
import { NavDropdown } from "./NavDropdown.client";
import { NavLink } from "./NavLink.client";
import { MobileDrawer } from "./MobileDrawer.client";
import { getNavigation } from "@/lib/payload-queries";

// Safety net used only if the CMS Navigation collection is empty/unreachable,
// so the menu never disappears. Matches the shape getNavigation() returns.
const FALLBACK_NAV_LINKS = [
  { label: "Bli medlem", href: "/bli-medlem" },
  { label: "Föreningen", href: "/foreningen" },
  { label: "Kontakt", href: "/styrelsen" },
  {
    label: "Lantraskaninen",
    href: "/lantraskaninen",
    children: [
      {
        label: "Gotlandskanin",
        href: "/gotlandskanin",
        subtitle: "~200 uppfödare",
        image: "/stamboken/breed-gotlandskanin.jpg",
      },
      {
        label: "Mellerudskanin",
        href: "/mellerudskanin",
        subtitle: "~50 genbanksbesättningar",
        image: "/stamboken/breed-mellerudskanin.jpg",
      },
      {
        label: "Bli genbanksbesättning",
        href: "/bli-genbanksbesattning",
        subtitle: "så går det till",
      },
    ],
  },
  { label: "Historik", href: "/historik" },
  { label: "Forum", href: "/medlemsforum" },
];

export async function PublicNav() {
  const cmsLinks = await getNavigation();
  const NAV_LINKS = cmsLinks.length ? cmsLinks : FALLBACK_NAV_LINKS;
  return (
    <Box
      component="header"
      sx={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        bgcolor: "paper.main",
        borderBottom: 1,
        borderColor: "line.main",
        px: { xs: 4, md: 6, lg: 10 },
        py: 3.5,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 3,
      }}
    >
      {/* Logo + wordmark */}
      <Link
        href="/"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "12px",
          textDecoration: "none",
          color: "inherit",
        }}
      >
        <Box
          sx={{
            width: 44,
            height: 44,
            borderRadius: "50%",
            overflow: "hidden",
            flexShrink: 0,
          }}
        >
          <Image
            src="/stamboken/logo.png"
            alt="Föreningen Gotlandskaninen"
            width={44}
            height={44}
            priority
          />
        </Box>
        <Box sx={{ lineHeight: 1 }}>
          <Typography
            sx={{
              fontFamily: "'Source Serif 4', Georgia, serif",
              fontSize: { xs: "15px", sm: "17px" },
              fontWeight: 500,
              letterSpacing: "-0.01em",
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
              // From lg only: at 900 px the tagline, the inline nav and the
              // CTA together overflow the viewport (horizontal scroll).
              display: { xs: "none", lg: "block" },
              whiteSpace: "nowrap",
            }}
          >
            Bevarar svenska lantraskaniner sedan 1984
          </Typography>
        </Box>
      </Link>

      {/* Desktop navigation */}
      <Box
        component="nav"
        sx={{
          display: { xs: "none", md: "flex" },
          alignItems: "center",
          gap: { md: 3.5, lg: 6 },
        }}
      >
        {NAV_LINKS.map((link) =>
          link.children ? (
            <NavDropdown
              key={link.href}
              label={link.label}
              href={link.href}
              items={link.children}
            />
          ) : (
            <NavLink key={link.href} href={link.href} label={link.label} />
          ),
        )}
      </Box>

      {/* Right: Stamboken CTA */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 3 }}>
        <LinkButton
          href="/stamboken-online"
          variant="contained"
          size="small"
          startIcon={
            <Box
              component="svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              sx={{
                width: 14,
                height: 14,
              }}
            >
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx={12} cy={7} r={4} />
            </Box>
          }
          sx={{ display: { xs: "none", md: "inline-flex" } }}
        >
          Stamboken
        </LinkButton>
        <MobileDrawer
          links={NAV_LINKS}
          cta={{ label: "Stamboken", href: "/stamboken-online" }}
        />
      </Box>
    </Box>
  );
}
