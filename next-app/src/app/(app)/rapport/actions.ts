"use server";

import { fetchApi, ApiError } from "@/lib/api";
import type { ActionResult } from "../stamboken/(dashboard)/inkorg/actions";
import {
  SUBMIT_TIMEOUT_MS,
  type DraftData,
  type Receipt,
  type ReportView,
  type Refusal,
  type Submission,
} from "../stamboken/(dashboard)/arsrapport/lib";

// The report actions of the page behind the personal link. The same four as the logged-in page, with the same
// signatures so ReportForm can call either, but every call goes to the production API (the link works there only)
// and none checks the mode cookie: a visitor with a link has no sb_mode.
export type MineEntry = {
  code_id: number;
  herd: string;
  herd_name: string | null;
  year: number;
};

const HERD = /^[A-Z]{1,3}[0-9]{1,6}$/;

const refused = (detail: string): ActionResult<never> => ({
  ok: false,
  problem: { status: 400, title: "Ogiltig begäran", detail },
});

function path(herd: string, year: number, tail: string) {
  if (!HERD.test(herd) || !Number.isInteger(year) || year < 2000 || year > 2100)
    return null;
  return `/v2/arsrapport/besattning/${herd}/${year}${tail}`;
}

async function call<T>(
  url: string | null,
  method: string,
  body?: unknown,
  timeout?: number,
): Promise<ActionResult<T>> {
  if (url === null) return refused("Ogiltig besättning eller år.");
  try {
    const data = await fetchApi<T>(url, {
      method,
      forceProd: true,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(timeout ? { timeout } : {}),
    });
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
    // A dropped connection to the API: the caller shows "försök igen".
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

// The codes of the session (the page's own list), and the report of one herd.
export async function getMine() {
  return call<MineEntry[]>("/v2/rapport/mina", "GET");
}

export async function getReport(herd: string, year: number) {
  return call<ReportView>(path(herd, year, ""), "GET");
}

// The ReportForm arguments `env` and `post` belong to the logged-in page; the link has neither.
export async function saveDraft(
  herd: string,
  year: number,
  data: DraftData,
  updatedAt: string | null,
  key: string,
  revision: number | null,
) {
  return call<{ updated_at: string; submission_key: string | null }>(
    path(herd, year, "/utkast"),
    "PUT",
    { data, updated_at: updatedAt, submission_key: key, revision },
  );
}

export async function dryRun(herd: string, year: number, body: Submission) {
  return call<{ ok: boolean; refusals: Refusal[]; warnings: Refusal[] }>(
    path(herd, year, "/torrkorning"),
    "POST",
    body,
    SUBMIT_TIMEOUT_MS,
  );
}

export async function submitReport(
  herd: string,
  year: number,
  body: Submission,
) {
  return call<Receipt>(
    path(herd, year, "/skicka"),
    "POST",
    body,
    SUBMIT_TIMEOUT_MS,
  );
}

export async function withdrawReport(
  herd: string,
  year: number,
  revision: number,
  reason: string | undefined,
) {
  return call<ReportView>(
    path(herd, year, "/dra-tillbaka"),
    "POST",
    { revision, reason: reason ?? null },
    SUBMIT_TIMEOUT_MS,
  );
}

// The sale dialog's herd picker needs a login. Sales through the link come in step 4, so the list stays empty.
export async function getGenebankHerds(_genebankId: number) {
  return { success: false as const, error: "needs_login" };
}
