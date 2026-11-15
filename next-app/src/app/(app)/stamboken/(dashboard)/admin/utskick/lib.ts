export type MailStatus =
  | "queued"
  | "sending"
  | "sent"
  | "failed"
  | "bounced"
  | "blocked"
  | "logged"
  | "cancelled";

export type MailMessage = {
  id: number;
  kind: string;
  status: string;
  recipient: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
};

export type MailAlarm = { code: string; message: string };

export type MailList = {
  alarms: MailAlarm[];
  last_run_at: string | null;
  paused_until: string | null;
  last_sent_at: string | null;
  items: MailMessage[];
};

export const STATUS_LABEL: Record<MailStatus, string> = {
  queued: "Köad",
  sending: "Skickas",
  sent: "Skickad",
  failed: "Misslyckades",
  bounced: "Studsade",
  blocked: "Spärrad",
  logged: "Loggad",
  cancelled: "Stoppad",
};

const ALARM_TEXT: Record<string, string> = {
  relay_refusing:
    "Reläet tar inte emot e-post från servern. Kontrollera reläets inställningar.",
  queue_stalled: "Kön står still. Schemaläggaren kör inte.",
};

export const statusLabel = (status: string): string =>
  STATUS_LABEL[status as MailStatus] ?? status;

export const alarmText = (a: MailAlarm): string =>
  ALARM_TEXT[a.code] ?? a.message;

/** Which row action applies: retry on failed/bounced, stop on queued. */
export function rowAction(status: string): "retry" | "cancel" | null {
  if (status === "failed" || status === "bounced") return "retry";
  return status === "queued" ? "cancel" : null;
}

export function formatTime(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString("sv-SE", { timeZone: "Europe/Stockholm" });
}

export function isFuture(value: string | null, now = Date.now()): boolean {
  return !!value && new Date(value).getTime() > now;
}
