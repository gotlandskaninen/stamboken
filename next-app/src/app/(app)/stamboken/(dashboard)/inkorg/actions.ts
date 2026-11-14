"use server";

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";
import type { InboxDocument, InboxItem, Problem, Rect } from "./lib";

// Every mutation of the queue, as docs/inkorg.md describes it. Flask decides;
// a refusal comes back as the whole problem so the form can place it.
export type ActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; problem: Problem };
type DocResult = { item: InboxItem; document: InboxDocument };

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
const DOCUMENT_FIELDS = ["doc_type", "cert_format", "rotation", "dismissed"];

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
    revalidatePath(LIST);
    if (itemId !== null) revalidatePath(`${LIST}/${itemId}`);
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

export async function takeItem(id: number, over = false) {
  if (!isId(id)) return refused("Ogiltigt ärende.");
  return call<InboxItem>(id, `/${id}/${over ? "ta-over" : "ta"}`, "POST");
}

export async function assignItem(id: number, userId: number) {
  if (!isId(id) || !isId(userId)) return refused("Välj en person.");
  return call<InboxItem>(id, `/${id}/tilldela`, "POST", { user_id: userId });
}

export async function assignHerd(herd: string, userId: number) {
  if (typeof herd !== "string" || !herd.trim() || !isId(userId))
    return refused("Ange besättningsnummer och välj en person.");
  return call<{ assigned: number[] }>(null, "/tilldela", "POST", {
    herd: herd.trim().toUpperCase(),
    user_id: userId,
  });
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
) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
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

export async function registerSale(
  id: number,
  doc: number,
  payload: { individual: string; herd: string; date: string },
) {
  if (!isId(id) || !isId(doc)) return refused("Ogiltigt dokument.");
  return call<DocResult>(id, `/${id}/dokument/${doc}/overlat`, "POST", payload);
}

/**
 * The rectangles come with the rotation they were drawn in (fractions of the
 * image as turned by it): the API stores both and makes the copy from the pair.
 * An empty list needs `noPersonalData`, the handler's explicit "nothing to hide".
 */
export async function confirmMask(
  id: number,
  doc: number,
  rotation: number,
  rects: Rect[],
  noPersonalData = false,
) {
  if (!isId(id) || !isId(doc) || !Array.isArray(rects))
    return refused("Ogiltig maskning.");
  if (![0, 90, 180, 270].includes(rotation))
    return refused("Ogiltig vridning.");
  if (rects.length === 0 && noPersonalData !== true)
    return refused("Bekräfta att fotot inte visar några uppgifter.");
  return call<DocResult>(id, `/${id}/dokument/${doc}/maskning`, "POST", {
    rotation,
    mask_rects: rects,
    ...(rects.length === 0 ? { no_personal_data: true } : {}),
  });
}

export type RegistryRabbit = {
  name: string | null;
  color: string | null;
  mother: { number: string; name: string | null } | null;
  father: { number: string; name: string | null } | null;
};

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
