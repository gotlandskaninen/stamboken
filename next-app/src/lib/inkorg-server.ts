import { cache } from "react";
import { notFound } from "next/navigation";
import { fetchApi } from "./api";
import type { InboxCount } from "./inkorg";
import type { Person } from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

/** The menu's counter and whether the user works in the queue; one call per request, shared by layout and pages. */
export const getInboxCount = cache(() =>
  fetchApi<InboxCount>("/v2/inkorg/notiser/antal"),
);

/** The Inkorg pages are for the queue's workers; 404 for everyone else, as the admin pages do (no enumeration). */
export async function requireQueueWorker(): Promise<void> {
  if (!(await getInboxCount()).works_in_queue) notFound();
}

/** Everyone the queue can assign to: id and name only (GET /v2/inkorg/handlaggare). */
export const fetchHandlers = () =>
  fetchApi<{ people: Person[] }>("/v2/inkorg/handlaggare")
    .then((r) => r.people)
    .catch(() => []);
