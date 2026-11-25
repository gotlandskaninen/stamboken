"use server";

import { fetchApi, ApiError } from "@/lib/api";
import type { GenebankHerd } from "@/utils/saleRules";
import type { ActionResult } from "../stamboken/(dashboard)/inkorg/actions";
import {
  reportLinkPath,
  SUBMIT_TIMEOUT_MS,
  type DraftData,
  type Father,
  type Litter,
  type LitterBody,
  type PurchaseBody,
  type PurchasePhotosBody,
  type PurchaseNotice,
  type Receipt,
  type ReportView,
  type Refusal,
  type Submission,
} from "../stamboken/(dashboard)/arsrapport/lib";

// The report actions of the page behind the personal link. The same four as the logged-in page, with the same
// signatures so ReportForm can call either, but every call goes to the production API (the link works there only)
// and the report code authorizes the herd and year, also for a signed-in visitor.
export type MineEntry = {
  code_id: number;
  herd: string;
  herd_name: string | null;
  year: number;
};

const HERD = /^[A-Z]{1,3}[0-9]{1,6}$/;

const refused = (detail: string): ActionResult<never> => ({
  ok: false,
  problem: { status: 400, title: "Fel i adressen", detail },
});

function path(herd: string, year: number, tail: string) {
  if (!HERD.test(herd) || !Number.isInteger(year) || year < 2000 || year > 2100)
    return null;
  return reportLinkPath(`/v2/arsrapport/besattning/${herd}/${year}${tail}`);
}

async function call<T>(
  url: string | null,
  method: string,
  body?: unknown,
  options?: { timeout?: number },
): Promise<ActionResult<T>> {
  if (url === null)
    return refused(
      "Besättningen eller året i adressen stämmer inte. Öppna rapporten från länken i mejlet eller från Min besättning.",
    );
  try {
    const data = await fetchApi<T>(url, {
      method,
      forceProd: true,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...options,
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
    { timeout: SUBMIT_TIMEOUT_MS },
  );
}

export async function submitReport(
  herd: string,
  year: number,
  body: Submission,
) {
  return call<Receipt>(path(herd, year, "/skicka"), "POST", body, {
    timeout: SUBMIT_TIMEOUT_MS,
  });
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
    { timeout: SUBMIT_TIMEOUT_MS },
  );
}

export async function reportPurchase(
  herd: string,
  year: number,
  body: PurchaseBody,
) {
  return call<PurchaseNotice>(path(herd, year, "/kop"), "POST", body);
}

export async function sendPurchasePhotos(
  herd: string,
  year: number,
  body: PurchasePhotosBody,
) {
  return call<PurchaseNotice>(path(herd, year, "/kop/inskick"), "POST", body);
}

// The sale dialog's herd picker: the report herd's genebank, as the logged-in picker has it (4a). The page binds
// the herd and the year, so the dialog calls it with the genebank id alone, as it calls the logged-in one.
export async function getGenebankHerds(
  herd: string,
  year: number,
  _genebankId: number,
) {
  const res = await call<{ herds: GenebankHerd[] }>(
    path(herd, year, "/besattningar"),
    "GET",
  );
  return res.ok
    ? { success: true as const, herds: res.data.herds }
    : {
        success: false as const,
        error: res.problem.detail,
        status: res.problem.status,
      };
}

// "Kullar under Y": as the logged-in page's actions, without `env` and `post`.
export async function addLitter(herd: string, year: number, body: LitterBody) {
  return call<{ id: number; litters: Litter[] }>(
    path(herd, year, "/kull"),
    "POST",
    body,
  );
}

export async function changeLitter(
  herd: string,
  year: number,
  breedingId: number,
  body: { litter_size?: number; litter_size6w: number | null },
) {
  return call<{ id: number; litters: Litter[] }>(
    Number.isSafeInteger(breedingId) && breedingId > 0
      ? path(herd, year, `/kull/${breedingId}`)
      : null,
    "PATCH",
    body,
  );
}

export async function getFathers(herd: string, year: number) {
  return call<{ hanar: Father[] }>(path(herd, year, "/hanar"), "GET");
}

export async function getMothers(herd: string, year: number) {
  return call<{ honor: Father[] }>(path(herd, year, "/honor"), "GET");
}
