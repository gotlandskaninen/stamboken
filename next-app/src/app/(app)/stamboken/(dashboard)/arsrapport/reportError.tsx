import React from "react";
import { TyckTillLink } from "@/components/tyck-till/TyckTillDialog.client";

type Failure = { status?: number; detail?: string };

// fetchApi can supply an HTTP status line in place of a missing server detail.
export function reportError(
  what: string,
  action: string,
  problem: Failure = {},
) {
  const detail = problem.detail ?? "";
  const reason = detail.trim().replace(/^HTTP \d{3}(?: |$)/, "");
  if (
    reason &&
    !/^(Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout|Bad Request|Unprocessable (Entity|Content)|Not Found|Forbidden|Conflict|Too Many Requests)$/i.test(
      reason,
    )
  )
    return detail;
  return (
    <>
      {what} kunde inte {action} på grund av ett fel hos oss. Det du skrev finns
      kvar. Försök igen om en stund, eller rapportera felet via <TyckTillLink />{" "}
      (felkod {problem.status ?? "ÅR-01"}).
    </>
  );
}
