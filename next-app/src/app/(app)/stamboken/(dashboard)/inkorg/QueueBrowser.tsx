"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  QUEUE_MODES,
  kindLabel,
  queueHref,
  queueStatus,
  queueSubject,
  queueWait,
  type InboxItem,
  type QueueList,
  type QueueMode,
} from "./lib";
import { formatTime } from "@/lib/inkorg";
import type { InterpretationSummary } from "./lib";
import styles from "./inkorg.module.css";

export function InboxHeader({ reading }: { reading?: InterpretationSummary }) {
  const { t } = useTranslation();
  return (
    <header className={styles.inboxHeader}>
      <h1>{t("sidebar.inkorg")}</h1>
      {reading && reading.interpreter !== "av" && (
        <p>
          {t("queue.reading", { count: reading.waiting })}{" "}
          {reading.last_done_at &&
            t("queue.lastRead", { time: formatTime(reading.last_done_at) })}
        </p>
      )}
    </header>
  );
}

function QueueRow({
  item,
  userId,
  now,
}: {
  item: InboxItem;
  userId: number;
  now: number;
}) {
  const { t } = useTranslation();
  const end = item.closed_at ? Date.parse(item.closed_at) : now;
  const age = (end - Date.parse(item.received_at)) / 86_400_000;
  const flags = [
    item.maybe_blurry && "blurry",
    item.missing_proof && "noProof",
    item.stalled && "stalled",
    item.has_skipped && "skipped",
    !item.closed_at && !item.stalled && age > 2 && "longWait",
  ].filter((flag): flag is string => typeof flag === "string");
  const kind = t(`queue.kinds.${item.kind}`, {
    defaultValue: kindLabel(item.kind),
  });
  return (
    <>
      <div>
        <div className={styles.subject}>
          <span className={styles.caseNumber}>#{item.id}</span>{" "}
          {queueSubject(item, t)}
        </div>
        <div className={styles.rowMeta}>
          {item.sender?.name || item.sender_address || t("queue.unknownSender")}{" "}
          ·{" "}
          {item.herd ? (
            <span className={styles.herdCode}>{item.herd}</span>
          ) : (
            t("queue.unknownHerd")
          )}{" "}
          · {kind.toLocaleLowerCase()} ·{" "}
          {t("queue.photos", { count: item.documents })} ·{" "}
          {item.assigned_to
            ? t("queue.with", { name: item.assigned_to.name })
            : t("queue.untaken")}
        </div>
      </div>
      <div className={styles.rowSide}>
        <span
          className={`sb-badge ${styles.stateBadge}`}
          data-state={item.state}
        >
          {queueStatus(item, userId, t)}
        </span>
        <span className={styles.waitTime} data-late={age > 1}>
          {queueWait(item.received_at, end, t)}
        </span>
      </div>
      {flags.length > 0 && (
        <div className={styles.rowFlags}>
          {flags.map((flag) => (
            <span key={flag}>{t(`queue.flags.${flag}`)}</span>
          ))}
        </div>
      )}
    </>
  );
}

export function QueueBrowser({
  data,
  query,
  selected,
  userId,
  now,
  assignment,
  children,
}: {
  data: QueueList;
  query: string;
  selected: number | null;
  userId: number;
  now: number;
  assignment: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const params = new URLSearchParams(query);
  const mode = (params.get("mode") || "oppna") as QueueMode;
  const herd = params.get("herd") || "";
  const offset = Number(params.get("offset")) || 0;
  const input = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pane = useRef<HTMLElement>(null);
  const previous = useRef<{ selected: number | null; query: string } | null>(
    null,
  );
  useEffect(() => {
    const last = previous.current;
    previous.current = { selected, query };
    if (last?.selected === selected) return;
    if (selected !== null && pane.current) {
      pane.current.scrollTop = 0;
      if (!window.matchMedia("(min-width: 1100px)").matches) {
        pane.current.focus({ preventScroll: true });
        pane.current.scrollIntoView?.({ block: "start" });
      }
    } else if (last?.selected && last.query === query) {
      document.getElementById(`case-row-${last.selected}`)?.focus();
    }
  }, [selected, query]);
  const first = data.items[0]?.id;

  // Opening a detail marks it read. Only the wide layout automatically opens the first.
  useEffect(() => {
    if (selected !== null || first === undefined) return;
    const wide = window.matchMedia("(min-width: 1100px)");
    const selectFirst = () => {
      if (wide.matches)
        router.replace(queueHref(query, { arende: first }), { scroll: false });
    };
    selectFirst();
    wide.addEventListener("change", selectFirst);
    return () => wide.removeEventListener("change", selectFirst);
  }, [first, query, router, selected]);

  useEffect(() => {
    if (input.current && input.current !== document.activeElement)
      input.current.value = herd;
  }, [herd]);
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [query],
  );

  const filterHref = (changes: Record<string, string | null>) =>
    queueHref(query, { arende: null, offset: null, ...changes });
  const search = (value: string) => {
    router.replace(filterHref({ herd: value.trim().toUpperCase() || null }), {
      scroll: false,
    });
  };

  function arrow(event: KeyboardEvent<HTMLUListElement>) {
    if (
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      (event.key !== "ArrowDown" && event.key !== "ArrowUp")
    )
      return;
    const links = Array.from(event.currentTarget.querySelectorAll("a"));
    const index = links.indexOf(event.target as HTMLAnchorElement);
    if (index < 0) return;
    event.preventDefault();
    const next = links[index + (event.key === "ArrowDown" ? 1 : -1)];
    if (next) {
      next.focus({ preventScroll: true });
      next.scrollIntoView?.({ block: "nearest" });
      router.replace(next.getAttribute("href")!, { scroll: false });
    }
  }

  return (
    <div className={styles.queueGrid} data-show-item={selected !== null}>
      <aside className={styles.queueSidebar} aria-label={t("queue.modesLabel")}>
        <nav className={styles.modeNav} aria-label={t("queue.modesLabel")}>
          {QUEUE_MODES.map((value) => (
            <Link
              key={value}
              prefetch={false}
              scroll={false}
              href={filterHref({ mode: value === "oppna" ? null : value })}
              aria-current={mode === value ? "page" : undefined}
            >
              {t(`queue.modes.${value}`)} <span>{data.mode_counts[value]}</span>
            </Link>
          ))}
        </nav>
        <details className={styles.modeHelp}>
          <summary>{t("queue.helpTitle")}</summary>
          <dl>
            {QUEUE_MODES.map((value) => (
              <div key={value}>
                <dt>{t(`queue.modes.${value}`)}</dt>
                <dd>{t(`queue.help.${value}`)}</dd>
              </div>
            ))}
          </dl>
        </details>
        {assignment}
      </aside>
      <section className={styles.queueList} aria-label={t("queue.listLabel")}>
        <div className={styles.listToolbar}>
          <nav className={styles.scopeNav} aria-label={t("queue.scope")}>
            {(["mina", "alla"] as const).map((scope) => (
              <Link
                key={scope}
                href={filterHref({ scope })}
                prefetch={false}
                scroll={false}
                aria-current={data.scope === scope ? "page" : undefined}
              >
                {t(scope === "mina" ? "queue.myScope" : "queue.allScope")}
              </Link>
            ))}
          </nav>
          <form
            className={styles.herdSearch}
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              if (timer.current !== null) clearTimeout(timer.current);
              search(input.current?.value ?? "");
            }}
          >
            <input
              ref={input}
              type="search"
              className="sb-input"
              aria-label={t("queue.search")}
              placeholder={t("queue.search")}
              autoComplete="off"
              defaultValue={herd}
              onChange={(event) => {
                if (timer.current !== null) clearTimeout(timer.current);
                const value = event.target.value;
                timer.current = setTimeout(() => search(value), 250);
              }}
            />
          </form>
          <select
            className="sb-input"
            aria-label={t("queue.order")}
            value={params.get("order") || "oldest"}
            onChange={(event) =>
              router.replace(
                filterHref({
                  order: event.target.value === "newest" ? "newest" : null,
                  herd: input.current?.value.trim().toUpperCase() || null,
                }),
                { scroll: false },
              )
            }
          >
            <option value="oldest">{t("queue.oldest")}</option>
            <option value="newest">{t("queue.newest")}</option>
          </select>
        </div>
        <div className={styles.listMeta}>
          <span>{t("queue.count", { count: data.total })}</span>
          <span className={styles.keyHint}>{t("queue.keys")}</span>
        </div>
        {data.items.length ? (
          <ul className={`sb-card ${styles.caseList}`} onKeyDown={arrow}>
            {data.items.map((item) => (
              <li key={item.id}>
                <Link
                  href={queueHref(query, { arende: item.id })}
                  prefetch={false}
                  scroll={false}
                  id={`case-row-${item.id}`}
                  className={styles.queueRow}
                  aria-current={selected === item.id ? "true" : undefined}
                >
                  <QueueRow item={item} userId={userId} now={now} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className={`sb-card ${styles.emptyList}`}>
            <p>{t("queue.empty")}</p>
            <Link
              href={filterHref({ mode: null, herd: null })}
              className="sb-btn sb-btn-secondary"
              prefetch={false}
            >
              {t("queue.reset")}
            </Link>
          </div>
        )}
        {(offset > 0 || data.total > data.items.length) && (
          <nav className={styles.pagination} aria-label={t("queue.pages")}>
            {offset > 0 && (
              <Link
                className="sb-btn sb-btn-secondary"
                prefetch={false}
                href={queueHref(query, {
                  offset: Math.max(0, offset - 50) || null,
                  arende: null,
                })}
              >
                {t("queue.prev")}
              </Link>
            )}
            {offset + data.items.length < data.total && (
              <Link
                className="sb-btn sb-btn-secondary"
                prefetch={false}
                href={queueHref(query, { offset: offset + 50, arende: null })}
              >
                {t("queue.next")}
              </Link>
            )}
          </nav>
        )}
      </section>
      <section
        tabIndex={-1}
        ref={pane}
        className={styles.detailPane}
        aria-label={t("queue.caseLabel")}
      >
        {children ?? (
          <p className={styles.emptyPane}>{t("queue.selectCase")}</p>
        )}
      </section>
    </div>
  );
}
