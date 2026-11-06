/**
 * Simple IndexedDB-backed retry queue for failed photo uploads.
 * Stores compressed blobs keyed by individual number. On app load or
 * connectivity restore, pending uploads are retried automatically.
 *
 * No service worker — uses navigator.onLine + online event listener.
 */

const DB_NAME = "herdbook-uploads";
const STORE_NAME = "pending-photos";
const DB_VERSION = 1;

interface PendingUpload {
  number: string;
  blob: Blob;
  timestamp: number;
  attempts?: number;
}

export const MAX_ATTEMPTS = 3;
export const MAX_AGE_MS = 1000 * 60 * 60 * 24; // 24h

export function shouldRetry(item: { attempts?: number }): boolean {
  return (item.attempts ?? 0) < MAX_ATTEMPTS;
}

export function isExpired(item: { timestamp: number }, now: number): boolean {
  return now - item.timestamp >= MAX_AGE_MS;
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "number" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function savePendingUpload(
  number: string,
  blob: Blob,
): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put({
      number,
      blob,
      timestamp: Date.now(),
    } satisfies PendingUpload);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function getPendingUploads(): Promise<PendingUpload[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function removePendingUpload(number: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(number);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** Writes a PendingUpload record verbatim (preserves blob, timestamp, attempts). */
async function putPendingUpload(item: PendingUpload): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(item);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/**
 * Retry all pending uploads. Called on app load and when connectivity is restored.
 * Drops items that are expired (> MAX_AGE_MS old) or exhausted (>= MAX_ATTEMPTS).
 * Returns the number of successfully retried uploads.
 */
export async function retryPendingUploads(
  uploadFn: (number: string, blob: Blob) => Promise<void>,
): Promise<number> {
  const pending = await getPendingUploads();
  let retried = 0;
  const now = Date.now();

  for (const item of pending) {
    // Drop expired or exhausted items without attempting upload.
    if (isExpired(item, now) || !shouldRetry(item)) {
      await removePendingUpload(item.number);
      continue;
    }

    try {
      await uploadFn(item.number, item.blob);
      await removePendingUpload(item.number);
      retried++;
    } catch {
      const nextAttempts = (item.attempts ?? 0) + 1;
      if (nextAttempts >= MAX_ATTEMPTS) {
        await removePendingUpload(item.number);
      } else {
        await putPendingUpload({ ...item, attempts: nextAttempts });
      }
    }
  }

  return retried;
}
