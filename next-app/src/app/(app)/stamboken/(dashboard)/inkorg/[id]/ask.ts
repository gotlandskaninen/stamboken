"use server";

import { revalidatePath } from "next/cache";
import { ApiError, fetchApi } from "@/lib/api";
import type { ActionResult } from "../actions";
import type { InboxItem, Rect } from "../lib";

const isId = (n: unknown): n is number =>
  Number.isSafeInteger(n) && (n as number) > 0;

/**
 * "Fråga uppfödaren" (POST …/fraga, docs/inkorg.md): the question to the
 * herd's holder, and the framed part of a document's photo when there is one.
 */
export async function askBreeder(
  id: number,
  text: string,
  part: { document: number; crop: Rect } | null = null,
): Promise<ActionResult<InboxItem>> {
  if (!isId(id) || typeof text !== "string" || (part && !isId(part.document)))
    return {
      ok: false,
      problem: {
        status: 400,
        title: "Ogiltig begäran",
        detail: "Skriv frågan.",
      },
    };
  const body = part
    ? { text, document: part.document, crop: part.crop }
    : { text };
  try {
    const data = await fetchApi<InboxItem>(`/v2/inkorg/${id}/fraga`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    revalidatePath("/stamboken/inkorg");
    revalidatePath(`/stamboken/inkorg/${id}`);
    return { ok: true, data };
  } catch (e) {
    if (e instanceof ApiError)
      return {
        ok: false,
        problem: {
          status: e.status,
          title: e.title,
          detail: e.detail,
          extensions: e.extensions,
        },
      };
    throw e;
  }
}
