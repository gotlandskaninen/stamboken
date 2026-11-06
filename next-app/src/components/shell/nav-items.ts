import type { SbIconName } from "./SbIcon";

// Single source of truth for the dashboard's primary nav (topbar + mobile).
// i18nKey reuses the existing sidebar.* keys (messages/*.json) so the copy and
// the i18n e2e assertions stay valid after the template sidebar's removal.
// Deliberately breeder-facing only: role-gated surfaces —
// Adminpanel and the /medlem section — live in AvatarMenu (Task A6),
// never as topbar links.
export const NAV_ITEMS: {
  key: string;
  i18nKey: string;
  href: string;
  icon: SbIconName;
}[] = [
  {
    key: "min-besattning",
    i18nKey: "sidebar.minBesattning",
    href: "/stamboken/min-besattning",
    icon: "home",
  },
  {
    key: "alla-kaniner",
    i18nKey: "sidebar.allaKaniner",
    href: "/stamboken/alla-kaniner",
    icon: "search",
  },
  {
    key: "genetik",
    i18nKey: "sidebar.genetik",
    href: "/stamboken/genetik",
    icon: "dna",
  },
  {
    key: "provparning",
    i18nKey: "sidebar.provparning",
    href: "/stamboken/provparning",
    icon: "heart",
  },
  {
    key: "profil",
    i18nKey: "sidebar.profil",
    href: "/stamboken/profil",
    icon: "user",
  },
];
