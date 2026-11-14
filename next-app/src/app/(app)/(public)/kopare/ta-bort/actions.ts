"use server";

import { ApiError, fetchApi } from "@/lib/api";

export type EraseResult = "removed" | "already_removed" | "invalid" | "error";

/**
 * The button on the erase link's page. The token goes in the body, never in a
 * URL. The API answers 404 to every token that is not genuine, whatever it names.
 */
export async function eraseBuyer(token: string): Promise<EraseResult> {
  try {
    const data = await fetchApi<{ result: "removed" | "already_removed" }>(
      "/v2/kopare/ta-bort",
      {
        method: "POST",
        body: JSON.stringify({ token }),
        // Public page: the buyer is in prod, also for a signed-in visitor in demo mode.
        forceProd: true,
      },
    );
    return data.result;
  } catch (err) {
    return err instanceof ApiError && err.status === 404 ? "invalid" : "error";
  }
}
