"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { MODE_COOKIE, parseMode, type Mode } from "@/lib/mode";
import type { SaleBuyer } from "@/components/individual/BuyerFields";
import { fetchApi, ApiError } from "@/lib/api";
import { crops, toApiFrame } from "./image";
import type {
  InboxDocument,
  InboxItem,
  Problem,
  Rect,
  shownAssignment,
} from "./lib";

// Every mutation of the queue, as docs/inkorg.md describes it. Flask decides;
// a refusal comes back as the whole problem so the form can place it.
export type ActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; problem: Problem };
type DocResult = { item: InboxItem; document: InboxDocument };
type AssignmentResult = InboxItem & { undo: string | null };
export type HerdPreview = {
  total: number;
  assignees: { id: number; name: string; count: number }[];
  revision: string;
};

const LIST = "/stamboken/inkorg";
const STATES = [
  "tagen",
  "vantar_foralder",
  "hos_genbanksansvarig",
  "ofullstandig",
  "klar",
  "dubblett",
  "skrap",
];
const DOCUMENT_FIELDS = [
  "doc_type",
  "cert_format",
  "rotation",
  "straighten",
  "dismissed",
];

const refused = (detail: string): ActionResult<never> => ({
  ok: false,
  problem: { status: 400, title: "Ogiltig begäran", detail },
});

// Server actions take any arguments from the browser: ids go into the URL.
const isId = (n: unknown): n is number =>
  Number.isSafeInteger(n) && (n as number) > 0;

async function call<T>(
  itemId: number | null,
  path: string,
  method: string,
  body?: unknown,
): Promise<ActionResult<T>> {
  const refresh = () => {
    if (method === "GET") return;
    if (itemId === null) revalidatePath(LIST, "layout");
    else {
      revalidatePath(LIST);
      revalidatePath(`${LIST}/${itemId}`);
    }
  };
  try {
    const data = await fetchApi<T>(`/v2/inkorg${path}`, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    refresh();
    return { ok: true, data };
  } catch (e) {
    if (e instanceof ApiError) {
      // Someone else changed the item: the view must show how it stands now.
      if (e.status === 409) refresh();
      return {
        ok: false,
        problem: {
          status: e.status,
          title: e.title,
          detail: e.detail,
          extensions: e.extensions,
        },
      };
    }
    // A timeout or a dropped connection to the API: a refusal the form can
    // show, so that what the handler typed stays on the screen.
    return {
      ok: false,
      problem: {
        status: 502,
        title: "Bad Gateway",
        detail: "Det gick inte att nå servern. Försök igen.",
      },
    };
  }
}

export async function takeItem(
  id: number,
  expected?: ReturnType<typeof shownAssignment>,
) {
  if (!isId(id)) return refused("Ogiltigt ärende.");
  return expected
    ? call<AssignmentResult>(id, `/${id}/ta-over`, "PUT", expected)
    : call<AssignmentResult>(id, `/${id}/ta`, "POST");
}

export async function releaseItem(id: number) {
  if (!isId(id)) return refused("Ogiltigt ärende.");
  return call<AssignmentResult>(id, `/${id}/slapp`, "POST");
}

export async function assignItem(id: number, userId: number) {
  if (!isId(id) || !isId(userId)) return refused("Välj en person.");
  return call<AssignmentResult>(id, `/${id}/tilldela`, "POST", {
    user_id: userId,
  });
}

export async function previewHerd(herd: string) {
  if (typeof herd !== "string" || !herd.trim())
    return refused("Ange besättningsnummer.");
  const query = new URLSearchParams({ herd: herd.trim().toUpperCase() });
  return call<HerdPreview>(null, `/tilldela?${query}`, "GET");
}

export async function assignHerd(
  herd: string,
  userId: number,
  revision: string,
) {
  if (typeof herd !== "string" || !herd.trim() || !isId(userId))
    return refused("Ange besättningsnummer och välj en person.");
  if (typeof revision !== "string" || !revision)
    return refused("Kontrollera vilka ärenden som ska tilldelas.");
  return call<{ assigned: number[]; undo: string | null }>(
    null,
    "/tilldela",
    "POST",
    {
      herd: herd.trim().toUpperCase(),
      user_id: userId,
      revision,
    },
  );
}

export async function undoAssignment(undo: string) {
  if (typeof undo !== "string" || !undo) return refused("Ogiltig ändring.");
  return call<{ restored: number[]; warning?: string }>(
    null,
    "/angra",
    "POST",
    { undo },
  );
}

export async function changeState(
  id: number,
  state: string,
  extra: { note?: string; duplicate_of?: number } = {},
) {
  if (!isId(id) || !STATES.includes(state)) return refused("Okänt läge.");
  const body: Record<string, unknown> = { state };
  if (typeof extra.note === "string") body.note = extra.note;
  if (extra.duplicate_of !== undefined) {
    if (!isId(extra.duplicate_of))
      return refused("Ange numret på det andra ärendet.");
    body.duplicate_of = extra.duplicate_of;
  }
  return call<InboxItem>(id, `/${id}/lage`, "POST", body);
}

export async function updateDocument(
  id: number,
  doc: number,
  changes: Record<string, unknown>,
  // A caller that lives on after an environment switch (paper entry) says which
  // environment it expects; the cookie must agree.
  env?: Mode,
) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  if (env && parseMode((await cookies()).get(MODE_COOKIE)?.value) !== env)
    return refused("Miljön har bytts. Ladda om sidan.");
  const body = Object.fromEntries(
    Object.entries(changes ?? {}).filter(([k]) => DOCUMENT_FIELDS.includes(k)),
  );
  return call<DocResult>(id, `/${id}/dokument/${doc}`, "PATCH", body);
}

/** "Väntar på förälder": the parent's number on the document, then the state. */
export async function waitForParent(
  id: number,
  doc: number,
  numbers: string[],
) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  if (!Array.isArray(numbers) || numbers.some((n) => typeof n !== "string"))
    return refused("Ange förälderns nummer.");
  const waiting = await call<DocResult>(id, `/${id}/dokument/${doc}`, "PATCH", {
    waiting_for: numbers.map((n) => n.trim().toUpperCase()).filter(Boolean),
  });
  if (!waiting.ok) return waiting;
  return call<InboxItem>(id, `/${id}/lage`, "POST", {
    state: "vantar_foralder",
  });
}

/**
 * "Hitta pappret": the straighten that lines up the photo's writing, and the
 * paper in fractions of the photo turned by its saved rotation plus that
 * angle. With `straighten` (the masking step) the angle is that one and is
 * not looked for. Nothing is changed: the view applies it.
 */
export async function findPaper(id: number, doc: number, straighten?: number) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  if (
    straighten !== undefined &&
    (!Number.isFinite(straighten) || Math.abs(straighten) > 15)
  )
    return refused("Ogiltig vinkel.");
  return call<{ angle: number; paper: Rect | null }>(
    id,
    `/${id}/dokument/${doc}/hitta-pappret`,
    "POST",
    straighten === undefined ? undefined : { straighten },
  );
}

/** "Tolka igen": the certificate waits for the image reading again, after a turn. */
export async function reinterpretDocument(id: number, doc: number) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  return call<DocResult>(id, `/${id}/dokument/${doc}/tolka-igen`, "POST");
}

export async function saveCertificate(
  id: number,
  doc: number,
  payload: Record<string, unknown>,
) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  return call<DocResult>(id, `/${id}/dokument/${doc}/spara`, "POST", payload);
}

/** A report photo compared with its rabbit: "Stämmer", or "Rättat" when the rabbit was corrected; it closes. */
export async function checkReportPhoto(
  id: number,
  doc: number,
  outcome: "stammer" | "rattat",
) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  if (outcome !== "stammer" && outcome !== "rattat")
    return refused("Välj Stämmer eller Rättat.");
  return call<DocResult>(id, `/${id}/dokument/${doc}/kontrollerad`, "POST", {
    outcome,
  });
}

export async function registerSale(
  id: number,
  doc: number,
  payload: {
    individual: string;
    herd: string;
    date: string;
    buyer?: SaleBuyer;
  },
) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  return call<DocResult>(id, `/${id}/dokument/${doc}/overlat`, "POST", payload);
}

/**
 * The rectangles and the frame come with the rotation and the straighten they
 * were drawn in (fractions of the image as turned by both): the API stores
 * them together and makes the copy from them, cropped to the frame (null: the
 * whole photo).
 * Neither boxes nor a frame needs `noPersonalData`, the handler's explicit
 * "nothing to hide".
 * `matchesRegistry`: the handler found the certificate and the registry in agreement.
 */
export async function confirmMask(
  id: number,
  doc: number,
  rotation: number,
  straighten: number,
  rects: Rect[],
  frame: Rect | null,
  noPersonalData = false,
  matchesRegistry = false,
) {
  if (!isId(id) || !isId(doc) || !Array.isArray(rects))
    return refused("Ogiltig maskning.");
  if (![0, 90, 180, 270].includes(rotation))
    return refused("Ogiltig vridning.");
  if (!Number.isFinite(straighten) || Math.abs(straighten) > 15)
    return refused("Ogiltig vinkel.");
  if (rects.length === 0 && !crops(frame) && noPersonalData !== true)
    return refused("Bekräfta att fotot inte visar några uppgifter.");
  return call<DocResult>(id, `/${id}/dokument/${doc}/maskning`, "POST", {
    rotation,
    straighten,
    mask_rects: rects,
    copy_frame: frame && toApiFrame(frame),
    ...(rects.length === 0 && !crops(frame) ? { no_personal_data: true } : {}),
    matches_registry: matchesRegistry === true,
  });
}

export type RegistryRabbit = {
  name: string | null;
  color: string | null;
  mother: { number: string; name: string | null } | null;
  father: { number: string; name: string | null } | null;
};

/** An active move of a rabbit, and its buyer outside the association: there, none, or removed (never asked again). */
export type RegistrySale = {
  herd: string;
  date: string | null;
  kind: string;
  buyer: "present" | "none" | "removed";
};

/** The rabbit's active sales, read through the queue item (helpers too); an error when it cannot be read. */
export async function rabbitSales(id: number, number: string) {
  if (!isId(id) || !/^[A-Za-z]+\d+-\d{4,}$/.test(number.trim()))
    return refused("Ogiltigt individnummer.");
  return call<{ sales: RegistrySale[] }>(
    null,
    `/${id}/kanin/${encodeURIComponent(number.trim().toUpperCase())}/forsaljningar`,
    "GET",
  );
}

/** The registry's record of a parent, to compare with the photo; null when not found. */
export async function lookupRabbit(
  number: string,
): Promise<RegistryRabbit | null> {
  if (
    typeof number !== "string" ||
    !/^[A-Za-z]+\d+-\d{4,}$/.test(number.trim())
  )
    return null;
  try {
    const r = await fetchApi<RegistryRabbit>(
      `/v2/individual/${encodeURIComponent(number.trim().toUpperCase())}`,
    );
    return { name: r.name, color: r.color, mother: r.mother, father: r.father };
  } catch (e) {
    if (e instanceof ApiError) return null;
    throw e;
  }
}
