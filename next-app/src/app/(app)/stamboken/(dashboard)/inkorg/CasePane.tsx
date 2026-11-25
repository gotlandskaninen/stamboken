"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { formatTime } from "@/lib/inkorg";
import { AccountRef } from "./AccountRef";
import { ItemControls } from "./ItemControls";
import { AskForAttachment } from "./[id]/AskForAttachment";
import {
  MailThread,
  RabbitLinks,
  RelatedCase,
  SenderUnconfirmed,
  skippedFiles,
} from "./[id]/MailFacts";
import { CasePhotos } from "./[id]/PhotoViewer";
import {
  itemActions,
  kindLabel,
  lacksRole,
  queueStatus,
  queueSubject,
  queueWait,
  senderText,
  type InboxDetail,
  type QueueUser,
} from "./lib";
import styles from "./inkorg.module.css";

export function CasePane({
  item,
  user,
  myGenebanks,
  backHref,
  nextHref,
  now,
}: {
  item: InboxDetail;
  user: QueueUser;
  myGenebanks: number[] | null;
  backHref: string;
  nextHref: string | null;
  now: number;
}) {
  const { t } = useTranslation();
  const arrivalSubject = item.events.find((e) => e.kind === "inkommen")?.detail
    ?.subject;
  const subject = queueSubject(
    {
      kind: item.kind,
      subject:
        item.subject?.trim() ||
        (typeof arrivalSubject === "string" ? arrivalSubject : null),
    },
    t,
  );
  const skipped = item.events
    .map((event) => ({ event, files: skippedFiles(event) }))
    .filter(({ files }) => files.length > 0);
  const mentioned = item.mentioned_individuals ?? [];
  const canAsk =
    !lacksRole(user, item.genebank_id, myGenebanks) &&
    itemActions(item, user, myGenebanks).includes("ofullstandig") &&
    Boolean(item.sender || (item.sender_address && item.sender_authenticated));

  return (
    <article
      className={`sb-card ${styles.casePane}`}
      aria-labelledby="case-subject"
    >
      <Link
        href={backHref}
        scroll={false}
        prefetch={false}
        className={`sb-btn sb-btn-secondary ${styles.caseBack}`}
      >
        {t("queueDetail.back")}
      </Link>
      <h2 id="case-subject">
        <span className={styles.caseNumber}>#{item.id}</span> {subject}
      </h2>
      <div className={styles.caseStatus}>
        <span
          className={`sb-badge ${styles.stateBadge}`}
          data-state={item.state}
        >
          {queueStatus(item, user.id, t)}
        </span>
        {item.assigned_to ? (
          // Always a span: the "·" separators (.caseStatus span + span) count spans only.
          <span>
            {user.is_admin ? (
              <Link
                href={`/stamboken/admin/anvandare/${item.assigned_to.id}`}
                className="sb-link"
              >
                {t("queue.with", { name: item.assigned_to.name })}
              </Link>
            ) : (
              t("queue.with", { name: item.assigned_to.name })
            )}
          </span>
        ) : (
          item.state === "ny" && <span>{t("queue.untaken")}</span>
        )}
        <span>
          {item.herd
            ? t("queueDetail.herd", { herd: item.herd })
            : t("queue.unknownHerd")}
        </span>
        <span>
          {t("queueDetail.elapsed", {
            age: queueWait(item.received_at, now, t),
          })}
        </span>
      </div>
      <div className={styles.caseActions}>
        <ItemControls item={item} user={user} myGenebanks={myGenebanks} />
        {nextHref ? (
          <Link
            href={nextHref}
            scroll={false}
            prefetch={false}
            className="sb-btn sb-btn-secondary"
          >
            {t("queueDetail.next")}
          </Link>
        ) : (
          <button type="button" className="sb-btn sb-btn-secondary" disabled>
            {t("queueDetail.next")}
          </button>
        )}
      </div>
      {item.documents.length > 0 && (
        <CasePhotos itemId={item.id} documents={item.documents} />
      )}
      {skipped.map(({ event, files }) => (
        <section key={event.id} className={styles.caseSkipped}>
          <h3>
            {event.kind === "svar"
              ? t("queueDetail.skippedReply", { date: formatTime(event.at) })
              : t("queueDetail.skipped")}
          </h3>
          {files.map((file, i) => (
            <p key={i}>{file}</p>
          ))}
          {event.kind === "inkommen" && canAsk && (
            <AskForAttachment itemId={item.id} />
          )}
        </section>
      ))}
      <MailThread item={item} paneT={t} />
      {mentioned.length > 0 && (
        <section className={styles.caseSection}>
          <h3>{t("queueDetail.mentioned")}</h3>
          <RabbitLinks numbers={mentioned} />
        </section>
      )}
      <section className={styles.caseSection}>
        <h3>{t("queueDetail.about")}</h3>
        <dl className={styles.caseFacts}>
          <dt>{t("queueDetail.sender")}</dt>
          <dd>
            {/* senderText shows item.sender's name first. */}
            {item.sender ? (
              <AccountRef person={item.sender} user={user} />
            ) : (
              senderText(item) || t("queue.unknownSender")
            )}
            <SenderUnconfirmed item={item} paneT={t} />
          </dd>
          <dt>{t("queueDetail.kind")}</dt>
          <dd>
            {t(`queue.kinds.${item.kind}`, {
              defaultValue: kindLabel(item.kind),
            })}
          </dd>
          <dt>{t("queueDetail.received")}</dt>
          <dd>{formatTime(item.received_at)}</dd>
          <RelatedCase item={item} paneT={t} />
        </dl>
        <Link href={`/stamboken/inkorg/${item.id}`} prefetch={false}>
          {t("queueDetail.registration")}
        </Link>
      </section>
    </article>
  );
}
