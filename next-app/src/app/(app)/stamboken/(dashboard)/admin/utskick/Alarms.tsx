import ds from "@/styles/ds-admin.module.css";
import { alarmText, formatTime, isFuture, type MailList } from "./lib";

export function Alarms({
  data,
  now,
}: {
  data: Pick<MailList, "alarms" | "last_sent_at" | "paused_until">;
  now?: number;
}) {
  return (
    <>
      {data.alarms.map((a) => (
        <div
          key={a.code}
          role="alert"
          className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]}`}
        >
          {alarmText(a)}
        </div>
      ))}
      <p className="sb-meta">
        Senaste utskick: {formatTime(data.last_sent_at)}
        {isFuture(data.paused_until, now) &&
          ` · Pausad till ${formatTime(data.paused_until)}`}
      </p>
    </>
  );
}
