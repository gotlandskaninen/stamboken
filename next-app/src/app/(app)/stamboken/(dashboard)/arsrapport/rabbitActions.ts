"use server";

import { cookies } from "next/headers";
import { fetchApi, ApiError } from "@/lib/api";
import { MODE_COOKIE, parseMode, type Mode } from "@/lib/mode";
import type { Found } from "@/components/register/RegisterFromCertificate";
import type { ActionResult } from "../inkorg/actions";

// "Lägg till kanin från intyget" (4b): the certificate's photo, the registration and the form's lookups. `env` is
// the logged-in page's data environment, checked against the mode cookie as its other actions are; without it the
// call is the personal link's, which works against the production API only and has no mode cookie
// (rapport/actions.ts). Flask decides who may do what.

const HERD = /^[A-Z]{1,3}[0-9]{1,6}$/;

export type Registered = {
  id: number;
  number: string;
  item_id: number;
  listed: boolean; // on the report's list, so the page can set its row
};

function path(herd: string, year: number, tail: string) {
  if (!HERD.test(herd) || !Number.isInteger(year) || year < 2000 || year > 2100)
    return null;
  return `/v2/arsrapport/besattning/${herd}/${year}${tail}`;
}

async function call<T>(
  env: Mode | undefined,
  url: string | null,
  init: {
    method: string;
    body?: BodyInit;
    timeout?: number;
    isolateDemo?: boolean;
  },
): Promise<ActionResult<T>> {
  const refused = (detail: string): ActionResult<never> => ({
    ok: false,
    problem: { status: 400, title: "Ogiltig begäran", detail },
  });
  if (url === null) return refused("Ogiltig besättning eller år.");
  if (
    env !== undefined &&
    parseMode((await cookies()).get(MODE_COOKIE)?.value) !== env
  )
    return refused("Miljön har bytts. Ladda om sidan.");
  try {
    const data = await fetchApi<T>(url, {
      ...init,
      ...(env === undefined ? { forceProd: true } : {}),
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
    // A dropped connection: what was typed stays, and "Försök igen" sends again.
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

/** The certificate's photo (field `file`): a `kontroll` item in the queue. */
export async function uploadPhoto(
  herd: string,
  year: number,
  data: FormData,
  env?: Mode,
  // a purchase notice's photo, which is never read, or a bought rabbit's that is sent to the queue (S7)
  purpose?: "kop" | "inskick",
) {
  return call<{ item_id: number; document_id: number }>(
    env,
    path(herd, year, purpose ? `/foto?syfte=${purpose}` : "/foto"),
    { method: "POST", body: data, timeout: 60000, isolateDemo: true },
  );
}

/** The rabbit from its paper certificate, bound to the photo (`item_id`). */
export async function registerRabbit(
  herd: string,
  year: number,
  body: Record<string, unknown>,
  env?: Mode,
) {
  return call<Registered>(env, path(herd, year, "/kanin"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** The registry's record of a number: null when there is no such rabbit, undefined when it could not be read. */
export async function findRabbit(
  herd: string,
  year: number,
  number: string,
  env?: Mode,
): Promise<Found | null | undefined> {
  if (typeof number !== "string") return undefined;
  const res = await call<Found>(
    env,
    path(herd, year, `/kanin-sok?nummer=${encodeURIComponent(number)}`),
    { method: "GET" },
  );
  if (res.ok) return res.data;
  // "Saknas" only for no such rabbit: never for a 401, a 403 or the herd's own 404 (L10)
  return res.problem.extensions?.code === "saknas" ? null : undefined;
}

/** On opening: the genebank's colour names, and the actor ("code-12", "user-5") a browser draft is kept under. */
export async function getFormSetup(herd: string, year: number, env?: Mode) {
  return call<{ farger: string[]; aktor: string }>(
    env,
    path(herd, year, "/kanin-formular"),
    { method: "GET" },
  );
}

/** The individual number Stamboken would give a certificate of the litter, or null when it cannot tell. */
export async function suggestNumber(
  herd: string,
  year: number,
  breedingId: number,
  env?: Mode,
): Promise<string | null> {
  if (!Number.isSafeInteger(breedingId) || breedingId <= 0) return null;
  const res = await call<{ suggested?: string }>(
    env,
    path(herd, year, `/nummerforslag?breeding_id=${breedingId}`),
    { method: "GET" },
  );
  return res.ok ? (res.data.suggested ?? null) : null;
}
