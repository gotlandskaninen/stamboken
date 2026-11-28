"use server";

import { cookies } from "next/headers";
import { fetchApi, ApiError } from "@/lib/api";
import { MODE_COOKIE, parseMode, type Mode } from "@/lib/mode";
import type { ActionResult } from "../inkorg/actions";
import { reportYears, type QueueList, type RoundRow } from "../inkorg/lib";
import {
  SUBMIT_TIMEOUT_MS,
  todayStockholm,
  type Completion,
  type DraftData,
  type Father,
  type Litter,
  type LitterBody,
  type Matrikel,
  type PurchaseBody,
  type PurchasePhotosBody,
  type PurchaseNotice,
  type Receipt,
  type ReportView,
  type Refusal,
  type Round,
  type SaldState,
  type SaleProposalRow,
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
  options?: { timeout?: number; isolateDemo?: boolean },
): Promise<ActionResult<T>> {
  if (url === null) return refused("Ogiltig besättning, år eller post.");
  if (parseMode((await cookies()).get(MODE_COOKIE)?.value) !== env)
    return refused("Miljön har bytts. Ladda om sidan.");
  try {
    const data = await fetchApi<T>(url, {
      method,
      body: JSON.stringify(body),
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

export async function saveAccount(
  herd: string,
  year: number,
  konto: NonNullable<Matrikel["konto"]>,
  env: Mode,
) {
  return call<{ konto: string }>(
    env,
    path(herd, year, "/konto"),
    "PUT",
    konto,
    {
      isolateDemo: true,
    },
  );
}

export async function saveReportContact(
  herd: string,
  year: number,
  field: "phone" | keyof NonNullable<Matrikel["adress"]>,
  value: string,
  env: Mode,
) {
  return call<{ ok: true }>(
    env,
    path(herd, year, "/kontakt"),
    "PATCH",
    { [field]: value },
    { isolateDemo: true },
  );
}

export async function requestReportEmailCode(
  herd: string,
  year: number,
  email: string,
  env: Mode,
) {
  return call<{ email_code_sent: boolean; email_refused?: string }>(
    env,
    path(herd, year, "/epost/kod"),
    "POST",
    { email },
    { isolateDemo: true },
  );
}

export async function cancelReportEmailCode(
  herd: string,
  year: number,
  env: Mode,
) {
  return call<void>(env, path(herd, year, "/epost/kod"), "DELETE", undefined, {
    isolateDemo: true,
  });
}

export async function verifyReportEmailCode(
  herd: string,
  year: number,
  code: string,
  env: Mode,
) {
  return call<void>(
    env,
    path(herd, year, "/epost/verifiera"),
    "POST",
    { code },
    {
      isolateDemo: true,
    },
  );
}

export async function saveReportConsent(
  herd: string,
  year: number,
  answer: Required<NonNullable<Matrikel["publicering"]>>,
  env: Mode,
) {
  return call<{ publicering_version: number }>(
    env,
    path(herd, year, "/publicering"),
    "PUT",
    answer,
    { isolateDemo: true },
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
    { timeout: SUBMIT_TIMEOUT_MS, isolateDemo: true },
  );
}

export async function submitReport(
  herd: string,
  year: number,
  body: Submission,
  env: Mode,
  post?: number,
) {
  return call<Receipt>(env, path(herd, year, "/skicka", post), "POST", body, {
    timeout: SUBMIT_TIMEOUT_MS,
    isolateDemo: true,
  });
}

export async function nextPaperForm(env: Mode): Promise<string> {
  const inbox = "/stamboken/inkorg";
  const rounds = await call<{ rounds: RoundRow[] }>(
    env,
    "/v2/arsrapport/rundor",
    "GET",
    undefined,
    { isolateDemo: true },
  );
  if (!rounds.ok) return inbox;
  const today = todayStockholm();
  let offset = 0;
  while (true) {
    const page = await call<QueueList>(
      env,
      `/v2/inkorg?paper_entry=1&offset=${offset}`,
      "GET",
      undefined,
      { isolateDemo: true },
    );
    if (!page.ok || !page.data.items.length) return inbox;
    let lost = 0;
    for (const item of page.data.items) {
      const years = reportYears(rounds.data.rounds, item.genebank_id, today);
      if (!item.herd || !years.length) continue;
      const taken = await call(
        env,
        `/v2/inkorg/${item.id}/ta`,
        "POST",
        { paper_entry: true },
        { isolateDemo: true },
      );
      if (!taken.ok) {
        if (![404, 409].includes(taken.problem.status)) return inbox;
        lost++;
        continue;
      }
      if (years.length > 1) return `${inbox}/${item.id}`;
      return `/stamboken/arsrapport/${item.herd}/${years[0]}?post=${item.id}`;
    }
    if (offset + page.data.items.length >= page.data.total) return inbox;
    offset += page.data.items.length - lost; // refused items have left the filtered queue
  }
}

export async function dryRunCompletion(
  herd: string,
  year: number,
  body: Completion,
  env: Mode,
) {
  return call<{ ok: boolean; refusals: Refusal[]; warnings: Refusal[] }>(
    env,
    path(herd, year, "/komplettera/torrkorning"),
    "POST",
    body,
    { timeout: SUBMIT_TIMEOUT_MS },
  );
}

export async function submitCompletion(
  herd: string,
  year: number,
  body: Completion,
  env: Mode,
) {
  return call<Receipt>(env, path(herd, year, "/komplettera"), "POST", body, {
    timeout: SUBMIT_TIMEOUT_MS,
  });
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
    { timeout: SUBMIT_TIMEOUT_MS },
  );
}

// The sale dialog's Spara: one rabbit's sale registered at once (Jonas 2026-11-26); 422 carries the refusals.
export async function sellNow(
  herd: string,
  year: number,
  individualId: number,
  sald: SaldState,
  env: Mode,
  post?: number,
) {
  if (!Number.isSafeInteger(individualId) || individualId <= 0)
    return refused("Ogiltig kanin.");
  return call<{ operation_id: string }>(
    env,
    path(herd, year, "/forsaljning", post),
    "POST",
    { individual_id: individualId, sald },
    { isolateDemo: true }, // a demo sale never reaches production, nor its buyer mail
  );
}

// Ångra a sale the view offers it for (`undo`): the report's route checks the seller's rule again now.
export async function undoSale(
  herd: string,
  year: number,
  herdTrackingId: number,
  operationId: string,
  env: Mode,
) {
  if (!Number.isSafeInteger(herdTrackingId) || herdTrackingId <= 0)
    return refused("Ogiltig försäljning.");
  return call<unknown>(
    env,
    path(herd, year, `/forsaljning/${herdTrackingId}/angra`),
    "POST",
    { operation_id: operationId },
    { isolateDemo: true },
  );
}

// "Kullar under Y": a litter is registered at once; the answer is the year's litters again.
export async function addLitter(
  herd: string,
  year: number,
  body: LitterBody,
  env: Mode,
  post?: number,
) {
  return call<{ id: number; litters: Litter[] }>(
    env,
    path(herd, year, "/kull", post),
    "POST",
    body,
  );
}

export async function changeLitter(
  herd: string,
  year: number,
  breedingId: number,
  body: { litter_size?: number; litter_size6w: number | null },
  env: Mode,
  post?: number,
) {
  return call<{ id: number; litters: Litter[] }>(
    env,
    Number.isSafeInteger(breedingId) && breedingId > 0
      ? path(herd, year, `/kull/${breedingId}`, post)
      : null,
    "PATCH",
    body,
  );
}

export async function getMothers(
  herd: string,
  year: number,
  env: Mode,
  post?: number,
) {
  return call<{ honor: Father[] }>(
    env,
    path(herd, year, "/honor", post),
    "GET",
    undefined,
  );
}

export async function getFathers(
  herd: string,
  year: number,
  env: Mode,
  post?: number,
) {
  return call<{ hanar: Father[] }>(
    env,
    path(herd, year, "/hanar", post),
    "GET",
    undefined,
  );
}

// "Anmäl köpet": a purchase notice for the genebank manager (4a Task 5).
export async function reportPurchase(
  herd: string,
  year: number,
  body: PurchaseBody,
  env: Mode,
) {
  return call<PurchaseNotice>(env, path(herd, year, "/kop"), "POST", body);
}

// "Skicka till genbanksansvarig": photos of a bought rabbit Stamboken lacks, to the queue (S7).
export async function sendPurchasePhotos(
  herd: string,
  year: number,
  body: PurchasePhotosBody,
  env: Mode,
) {
  return call<PurchaseNotice>(
    env,
    path(herd, year, "/kop/inskick"),
    "POST",
    body,
    { isolateDemo: true },
  );
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const isYear = (y: number) => Number.isInteger(y) && y >= 2000 && y <= 2100;

// Create the year's round, or move its dates. Only the dates given are sent.
export async function saveRound(
  year: number,
  dates: { start_date?: string; deadline?: string; end_date?: string },
  env: Mode,
) {
  const body: Record<string, string> = {};
  for (const key of ["start_date", "deadline", "end_date"] as const) {
    const value = dates[key];
    if (value === undefined) continue;
    if (!DATE.test(value)) return refused("Ange datumen som ÅÅÅÅ-MM-DD.");
    body[key] = value;
  }
  return call<Round>(
    env,
    isYear(year) ? `/v2/arsrapport/rundor/${year}` : null,
    "PUT",
    body,
  );
}

// The server sets send_at to the round's first day (the invitations come in step 3).
export async function activateGenebank(
  year: number,
  genebankId: number,
  env: Mode,
) {
  return call<Round>(
    env,
    isYear(year) && Number.isSafeInteger(genebankId) && genebankId > 0
      ? `/v2/arsrapport/rundor/${year}/genbanker/${genebankId}/aktivera`
      : null,
    "POST",
    {},
  );
}

// true = Ja, false = Nej, null = Räknas (the date of the report decides).
export async function setOnTime(
  herd: string,
  year: number,
  onTime: boolean | null,
  env: Mode,
) {
  return call<{ on_time_override: boolean | null }>(
    env,
    path(herd, year, "/i-tid"),
    "POST",
    { on_time: onTime },
  );
}

// "Ny länk": the herd's old link stops working and a new one is mailed to the main member.
export async function newLink(herd: string, year: number, env: Mode) {
  return call<{ sent: boolean }>(env, path(herd, year, "/ny-lank"), "POST", {});
}

// "Skicka påminnelse" queues a reminder for the herd.
export async function sendReminder(herd: string, year: number, env: Mode) {
  return call<{ queued: boolean }>(
    env,
    path(herd, year, "/paminnelse"),
    "POST",
    {},
  );
}

// "Koppla bort" (5.1): undo the account link a main member made with a code to the matrikel's e-mail.
export async function undoAccountLink(
  herd: string,
  year: number,
  linkId: number,
  env: Mode,
) {
  return call<{ ok: boolean }>(
    env,
    Number.isSafeInteger(linkId) && linkId > 0
      ? path(herd, year, `/kontokoppling/${linkId}/hav`)
      : null,
    "POST",
    {},
  );
}

// "Skicka provmejl till mig": the invitation without a link, to the manager's own address.
export async function sendTestMail(
  year: number,
  genebankId: number,
  env: Mode,
) {
  return call<{ queued: boolean }>(
    env,
    isYear(year) && Number.isSafeInteger(genebankId) && genebankId > 0
      ? `/v2/arsrapport/rundor/${year}/genbanker/${genebankId}/provmejl`
      : null,
    "POST",
    {},
  );
}

// The status view's sale dialog: the herd's pending proposals (manager or admin).
export async function saleProposals(herd: string, year: number, env: Mode) {
  return call<{ forslag: SaleProposalRow[] }>(
    env,
    path(herd, year, "/forslag"),
    "GET",
    undefined,
  );
}

const proposalPath = (id: number, action: "godkann" | "avvisa") =>
  Number.isSafeInteger(id) && id > 0
    ? `/v2/arsrapport/forslag/${id}/${action}`
    : null;

export async function approveSale(id: number, env: Mode) {
  return call<{ id: number; state: string }>(
    env,
    proposalPath(id, "godkann"),
    "POST",
    {},
  );
}

// The member is mailed the reason; "kvar" counts the rabbit on 31 December,
// "valj_igen" leaves it for the member to choose again.
export async function rejectSale(
  id: number,
  reason: string,
  then: "kvar" | "valj_igen",
  env: Mode,
) {
  return call<{ id: number; state: string }>(
    env,
    proposalPath(id, "avvisa"),
    "POST",
    { reason, then },
  );
}
