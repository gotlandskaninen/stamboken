"use server";

import { ApiError, fetchApi } from "@/lib/api";

type SubmitBody = {
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
  address?: string;
  postal_code?: string;
  city?: string;
  // Only when the applicant ticked "Fakturan ska till en annan adress".
  billing_name?: string;
  billing_address?: string;
  billing_postal_code?: string;
  billing_city?: string;
  billing_email?: string;
  billing_reference?: string;
  motivation?: string;
  gdpr_consent: boolean;
};

export type SubmitResult =
  | { ok: true; id: number }
  | { ok: false; error: string };

export async function submitApplication(
  body: SubmitBody,
): Promise<SubmitResult> {
  try {
    const data = await fetchApi<{ id: number; status: string }>(
      "/v2/member-applications",
      {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "Content-Type": "application/json" },
        // Public form: prod is the only real dataset, also for a signed-in
        // visitor whose sb_mode is demo.
        forceProd: true,
      },
    );
    return { ok: true, id: data.id };
  } catch (err) {
    return { ok: false, error: describeError(err) };
  }
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ?? err.title ?? "Något gick fel. Försök igen.";
  }
  return "Något gick fel. Försök igen.";
}
