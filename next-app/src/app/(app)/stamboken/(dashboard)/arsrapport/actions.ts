"use server";

import { cookies } from "next/headers";
import { fetchApi, ApiError } from "@/lib/api";
import { MODE_COOKIE, parseMode, type Mode } from "@/lib/mode";
import type { ActionResult } from "../inkorg/actions";
import {
  SUBMIT_TIMEOUT_MS,
  type DraftData,
  type Receipt,
  type ReportView,
  type Refusal,
  type Submission,
} from "./lib";

// Server actions take any arguments from the browser: the herd, the year and
// the post go into the URL, so they are checked first.
const HERD = /^[A-Z]{1,3}[0-9]{1,6}$/;

const refused = (detail: string): ActionResult<never> => ({
  ok: false,
  problem: { status: 400, title: "Ogiltig begäran", detail },
});

function path(herd: string, year: number, tail: string, post?: number) {
  if (!HERD.test(herd) || !Number.isInteger(year) || year < 2000 || year > 2100)
    return null;
  if (post !== undefined && !(Number.isSafeInteger(post) && post > 0))
    return null;
  const q = post === undefined ? "" : `?post=${post}`;
  return `/v2/arsrapport/besattning/${herd}/${year}${tail}${q}`;
}

// A call queued before an environment switch must not write into the other
// environment: the caller says which one it expects, the cookie must agree.
async function call<T>(
  env: Mode,
  url: string | null,
  method: string,
  body: unknown,
  timeout?: number,
): Promise<ActionResult<T>> {
  if (url === null) return refused("Ogiltig besättning, år eller post.");
  if (parseMode((await cookies()).get(MODE_COOKIE)?.value) !== env)
    return refused("Miljön har bytts. Ladda om sidan.");
  try {
    const data = await fetchApi<T>(url, {
      method,
      body: JSON.stringify(body),
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

export async function saveDraft(
  herd: string,
  year: number,
  data: DraftData,
  updatedAt: string | null,
  key: string,
  revision: number | null,
  env: Mode,
  post?: number,
) {
  return call<{ updated_at: string; submission_key: string | null }>(
    env,
    path(herd, year, "/utkast", post),
    "PUT",
    { data, updated_at: updatedAt, submission_key: key, revision },
  );
}

export async function dryRun(
  herd: string,
  year: number,
  body: Submission,
  env: Mode,
  post?: number,
) {
  return call<{ ok: boolean; refusals: Refusal[]; warnings: Refusal[] }>(
    env,
    path(herd, year, "/torrkorning", post),
    "POST",
    body,
    SUBMIT_TIMEOUT_MS,
  );
}

export async function submitReport(
  herd: string,
  year: number,
  body: Submission,
  env: Mode,
  post?: number,
) {
  return call<Receipt>(
    env,
    path(herd, year, "/skicka", post),
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
  env: Mode,
  post?: number,
) {
  return call<ReportView>(
    env,
    path(herd, year, "/dra-tillbaka", post),
    "POST",
    { revision, reason: reason ?? null },
    SUBMIT_TIMEOUT_MS,
  );
}
