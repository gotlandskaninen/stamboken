import type { Individual } from "@/redux/api/apiSlice";

export const STORAGE_PREFIX = "herdbook-edit-";

interface StoredFormData {
  formData: Partial<Individual>;
  savedAt: string;
}

export function saveFormData(
  number: string,
  formData: Partial<Individual>,
): void {
  const key = `${STORAGE_PREFIX}${number}`;
  const payload: StoredFormData = {
    formData,
    savedAt: new Date().toISOString(),
  };
  localStorage.setItem(key, JSON.stringify(payload));
}

export function loadFormData(
  number: string,
  serverUpdatedAt?: string | null,
): Partial<Individual> | null {
  const key = `${STORAGE_PREFIX}${number}`;
  const raw = localStorage.getItem(key);
  if (!raw) return null;

  try {
    const stored: StoredFormData = JSON.parse(raw);

    // Discard stale data if server is newer
    if (serverUpdatedAt && stored.savedAt) {
      const serverTime = new Date(serverUpdatedAt).getTime();
      const savedTime = new Date(stored.savedAt).getTime();
      if (serverTime > savedTime) {
        localStorage.removeItem(key);
        return null;
      }
    }

    return stored.formData;
  } catch (e) {
    // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring
    console.warn("Discarding corrupted form data for:", number, e);
    localStorage.removeItem(key);
    return null;
  }
}

export function clearFormData(number: string): void {
  localStorage.removeItem(`${STORAGE_PREFIX}${number}`);
}
