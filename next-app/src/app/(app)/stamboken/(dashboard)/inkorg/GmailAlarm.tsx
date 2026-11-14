import { fetchApi } from "@/lib/api";
import { formatTime } from "@/lib/inkorg";
import styles from "./inkorg.module.css";

type GmailStatus = {
  enabled: boolean;
  last_run_at: string | null;
  last_error: string | null;
  alarm: boolean;
};

/** One line at the top of the queue when reading the mailbox has stopped or failed (GET /v2/inkorg/status). */
export async function GmailAlarm() {
  const gmail = await fetchApi<{ gmail: GmailStatus }>("/v2/inkorg/status")
    .then((r) => r.gmail)
    .catch(() => null);
  if (!gmail?.alarm) return null;
  return (
    <p role="alert" className={styles.error}>
      {gmail.last_error
        ? `Fel vid inläsning av mejl: ${gmail.last_error}`
        : gmail.last_run_at
          ? `Mejlen har inte lästs in sedan ${formatTime(gmail.last_run_at)}.`
          : "Mejlen har inte lästs in än."}
    </p>
  );
}
