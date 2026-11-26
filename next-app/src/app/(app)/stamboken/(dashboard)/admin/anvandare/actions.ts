"use server";

import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";
import { requireAdminProdMode } from "../_lib/requireAdminProdMode";
import { generateTempPassword } from "../_lib/password";
import type { AdminUserListItem, PrivilegeEntry } from "../_lib/types";

const LIST_PATH = "/stamboken/admin/anvandare";

export type ActionError = { error: string };

// Every action stays on the account page (#249): the revalidation re-renders
// it with the new state, and the list keeps its search and filters.
function revalidateUser(userId: number) {
  revalidatePath(LIST_PATH);
  revalidatePath(`${LIST_PATH}/${userId}`);
}

export async function updateUserProfile(
  userId: number,
  fields: { fullname?: string; email?: string },
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    await fetchApi(`/v2/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function setV2ProdAccess(
  userId: number,
  enabled: boolean,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    await fetchApi(`/v2/admin/users/${userId}/v2-prod-access`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function setValidated(
  userId: number,
  validated: boolean,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    // Dedicated endpoint — the profile PATCH rejects flag fields.
    await fetchApi(`/v2/admin/users/${userId}/validated`, {
      method: "PATCH",
      body: JSON.stringify({ validated }),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function setAccountActive(
  userId: number,
  active: boolean,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    // Backend refuses self-deactivation and last-active-admin with 409.
    await fetchApi(`/v2/admin/users/${userId}/active`, {
      method: "PATCH",
      body: JSON.stringify({ active }),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function logoutEverywhere(
  userId: number,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    // A new mark for the account ends every session it has, also in the demo.
    await fetchApi(`/v2/admin/users/${userId}/logga-ut`, {
      method: "POST",
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function removeGoogleLogin(
  userId: number,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    await fetchApi(`/v2/admin/users/${userId}/google`, {
      method: "DELETE",
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function eraseAccount(
  userId: number,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    // #250: the backend refuses an account with a role or a person, one
    // already emptied and the admin's own (409 problem+json).
    await fetchApi(`/v2/admin/users/${userId}/erase`, {
      method: "POST",
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function grantRole(
  userId: number,
  role: PrivilegeEntry,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  try {
    await fetchApi("/v2/admin/role", {
      method: "POST",
      body: JSON.stringify({ operation: "add", user_id: userId, role }),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function revokeRole(
  userId: number,
  role: PrivilegeEntry,
): Promise<ActionError | void> {
  await requireAdminProdMode();
  if (role.level === "admin") {
    // Fast-feedback pre-check against the read side. Best-effort UX
    // only — the AUTHORITATIVE last-admin invariant is backend
    // (409 problem+json, type: last-admin), surfaced below as { error }.
    try {
      const list = await fetchApi<{ users: AdminUserListItem[] }>(
        "/v2/admin/users?role=admin&per_page=200",
        { forceProd: true },
      );
      const activeAdmins = list.users.filter((u) => u.is_active);
      const wouldEmptyAdminSet =
        activeAdmins.length <= 1 && activeAdmins.some((u) => u.id === userId);
      if (wouldEmptyAdminSet) {
        return {
          error:
            "Den sista administratörsrollen kan inte tas bort. Systemet " +
            "måste ha minst en administratör. Utse först en annan " +
            "administratör och försök sedan igen.",
        };
      }
    } catch {
      // Pre-check unavailable → fall through; backend still refuses.
    }
  }
  try {
    await fetchApi("/v2/admin/role", {
      method: "POST",
      body: JSON.stringify({ operation: "remove", user_id: userId, role }),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  revalidateUser(userId);
}

export async function resetPassword(
  userId: number,
): Promise<{ plaintext: string } | ActionError> {
  await requireAdminProdMode();
  const plaintext = generateTempPassword(); // crypto.randomBytes(16)
  try {
    // NEW dedicated endpoint (rate-limited 10/h per admin).
    // Body {"password": ...} covers BOTH change_password branches server-
    // side (INSERT for Google-only users, UPDATE otherwise). The legacy
    // /api/manage/setpassword routes are closed (410, ADR-0020).
    await fetchApi(`/v2/admin/users/${userId}/password-reset`, {
      method: "POST",
      body: JSON.stringify({ password: plaintext }),
      forceProd: true,
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.detail };
    throw e;
  }
  // Exception: no revalidation — the plaintext is shown
  // exactly once, and a reset of the admin's own password has already ended
  // her session, so a re-render would drop the page before she saw it.
  // [Klar] in the client refreshes the detail view.
  return { plaintext };
}
