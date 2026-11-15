// Pure helpers for the intake queue UI (docs/inkorg.md). No server imports,
// so client components and tests can use them.

export type InskickStatus =
  | "mottaget"
  | "under_arbete"
  | "fragat"
  | "klart"
  | "avslutat";

export interface Inskick {
  id: number;
  status: InskickStatus;
  received_at: string;
  herd: string;
  documents: number;
  individuals: string[];
}

export interface Notice {
  id: number;
  kind: string;
  text: string;
  item_id: number | null;
  created_at: string;
  read_at: string | null;
}

export interface InboxCount {
  unread: number;
  works_in_queue: boolean;
}

// The API sends UTC; the association reads Stockholm time. An explicit zone
// also keeps server and browser rendering the same text (no hydration mismatch).
const STHLM = { timeZone: "Europe/Stockholm" } as const;
export const formatTime = (iso: string) =>
  new Date(iso).toLocaleString("sv-SE", STHLM);
export const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("sv-SE", STHLM);

export const NO_INBOX: InboxCount = { unread: 0, works_in_queue: false };

export const STATUS_TEXT: Record<InskickStatus, string> = {
  mottaget: "Mottaget",
  under_arbete: "Under arbete",
  fragat: "Vi har frågat dig något",
  klart: "Klart",
  avslutat: "Avslutat",
};

export const STATUS_BADGE: Record<InskickStatus, string> = {
  mottaget: "",
  under_arbete: "sb-badge-himmel",
  fragat: "sb-badge-lera",
  klart: "sb-badge-mossa",
  avslutat: "",
};

export function statusText(status: string): string {
  return STATUS_TEXT[status as InskickStatus] ?? status;
}

export const WARNING_TEXT: Record<string, string> = {
  lag_upplosning: "Bilden har låg upplösning. Ta om den närmare?",
  suddig: "Bilden ser suddig ut. Ta om den?",
  for_mork: "Bilden är för mörk. Ta om den?",
  for_ljus: "Bilden är för ljus. Ta om den?",
};

export function warningText(code: string): string {
  return WARNING_TEXT[code] ?? "Bilden kan vara svår att läsa. Ta om den?";
}

export const MAX_SIDE = 3000;

export type ImagePlan =
  | { action: "keep" }
  | { action: "resize"; width: number; height: number };

/**
 * What to do with a picked file, given its type and decoded size (null when the
 * browser could not decode it). PDFs and anything undecodable are sent as is;
 * a JPEG already within MAX_SIDE is kept to avoid a second lossy pass; every
 * other decodable image is scaled to MAX_SIDE at most and re-encoded as JPEG.
 */
export function planImage(
  type: string,
  size: { width: number; height: number } | null,
): ImagePlan {
  if (!type.startsWith("image/") || !size) return { action: "keep" };
  const longest = Math.max(size.width, size.height);
  if (longest <= MAX_SIDE) {
    return type === "image/jpeg"
      ? { action: "keep" }
      : { action: "resize", width: size.width, height: size.height };
  }
  const ratio = MAX_SIDE / longest;
  return {
    action: "resize",
    width: Math.round(size.width * ratio),
    height: Math.round(size.height * ratio),
  };
}

/** Where a notice leads: `klar` goes to Mina inskick, the rest to the queue. */
export function noticeHref(n: Pick<Notice, "kind" | "item_id">): string {
  if (n.item_id == null) return "/stamboken/inskick";
  return n.kind === "klar"
    ? `/stamboken/inskick#arende-${n.item_id}`
    : `/stamboken/inkorg/${n.item_id}`;
}
