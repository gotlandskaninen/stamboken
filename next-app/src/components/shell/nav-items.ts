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

export type NavItem = (typeof NAV_ITEMS)[number];

// "Mina inskick" is for every logged-in user; "Inkorg" only for those who work
// in the intake queue (works_in_queue from /v2/inkorg/notiser/antal).
export function navItemsFor(worksInQueue: boolean): NavItem[] {
  return [
    ...NAV_ITEMS,
    {
      key: "inskick",
      i18nKey: "sidebar.minaInskick",
      href: "/stamboken/inskick",
      icon: "camera",
    },
    ...(worksInQueue
      ? [
          {
            key: "inkorg",
            i18nKey: "sidebar.inkorg",
            href: "/stamboken/inkorg",
            icon: "mail" as const,
          },
        ]
      : []),
  ];
}

// The unread-notice count is shown on Inkorg for queue workers (their notices
// are queue work) and on Mina inskick for everyone else ("klart" notices).
export function badgeKey(worksInQueue: boolean): string {
  return worksInQueue ? "inkorg" : "inskick";
}

export function badgeLabel(unread: number): string | null {
  if (unread <= 0) return null;
  return unread > 99 ? "99+" : String(unread);
}
