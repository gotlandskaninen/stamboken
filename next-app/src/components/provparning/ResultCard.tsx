"use client";

import React, { useState } from "react";
import NextLink from "next/link";
import { SbIcon, type SbIconName } from "@/components/shell/SbIcon";
import {
  RELATION_LABEL,
  VERDICT_LABEL,
  describeGenerations,
  formatOffspringF,
  formatPercent,
  type AnimalSummary,
  type TestbreedResult,
  type Thresholds,
  type Verdict,
} from "@/lib/provparning";
import { TestbreedTree } from "./TestbreedTree";
import styles from "./provparning.module.css";

// Avelsråd — the same document legacy's test mating links to.
export const AVELSRAD_URL =
  "https://drive.google.com/file/d/1GAC5Gjbq9KOQwxcDuAfGxHotfnpoaq-y/view?usp=share_link";

const VERDICT_STYLE: Record<Verdict, { cls: string; icon: SbIconName }> = {
  good: { cls: styles.verdictGood, icon: "check" },
  check: { cls: styles.verdictCheck, icon: "warn" },
  high: { cls: styles.verdictHigh, icon: "cross" },
};

const VISIBLE_ANCESTORS = 6;

export function individualHref(number: string) {
  return `/stamboken/individ/${encodeURIComponent(number)}`;
}

export function AnimalName({
  number,
  name,
  fallback,
}: {
  number: string | null;
  name: string | null;
  fallback: string;
}) {
  if (!number) return <>{fallback}</>;
  return (
    <>
      <NextLink className="sb-link" href={individualHref(number)}>
        {number}
      </NextLink>
      {name ? ` – ${name}` : ""}
    </>
  );
}

/** "F 1,2 % · MK 3,4 %" for a registered parent. */
export function ParentFacts({
  who,
  summary,
  fallback,
}: {
  who: string;
  summary: AnimalSummary;
  fallback: string;
}) {
  return (
    <li>
      {who}:{" "}
      <AnimalName
        number={summary.number}
        name={summary.name}
        fallback={fallback}
      />
      {summary.f != null && <> · F {formatPercent(summary.f)}</>}
      {summary.mk != null && <> · MK {formatPercent(summary.mk)}</>}
    </li>
  );
}

export function ResultCard({
  result,
  thresholds,
  femaleSummary,
  maleFallback,
  testId,
}: {
  result: TestbreedResult;
  thresholds: Thresholds;
  femaleSummary: AnimalSummary;
  /** Label for an unregistered male, e.g. "Oregistrerad hane (mor G1-1)". */
  maleFallback: string;
  testId: string;
}) {
  const [showTree, setShowTree] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const verdict = VERDICT_STYLE[result.verdict];
  const ancestors = showAll
    ? result.common_ancestors
    : result.common_ancestors.slice(0, VISIBLE_ANCESTORS);
  const hidden = result.common_ancestors.length - ancestors.length;
  const highlight = new Set(result.common_ancestors.map((a) => a.number));

  return (
    <article className={`sb-card ${styles.card}`} data-testid={testId}>
      <div className={styles.cardHead}>
        <h3 className={styles.maleName}>
          <AnimalName
            number={result.male.number}
            name={result.male.name}
            fallback={maleFallback}
          />
        </h3>
        <span
          className={`${styles.verdict} ${verdict.cls}`}
          data-testid="verdict"
          data-verdict={result.verdict}
        >
          <SbIcon name={verdict.icon} size={16} />
          {VERDICT_LABEL[result.verdict]}
        </span>
      </div>

      <div>
        <div className={styles.fRow}>
          <span className={styles.fLabel}>F</span>
          <span className={styles.fNum} data-testid="offspring-f">
            {formatOffspringF(result.offspring_f, thresholds)}
          </span>
        </div>
        <p className={styles.sentence}>
          Avkomman får inavelsgraden{" "}
          {formatOffspringF(result.offspring_f, thresholds)}. Den är lika med
          släktskapen mellan föräldrarna.
        </p>
      </div>

      {result.relation && (
        <div
          className={styles.warn}
          role="alert"
          data-testid="relation-warning"
        >
          <SbIcon name="warn" size={18} />
          <span>
            <strong>Nära släkt.</strong> {RELATION_LABEL[result.relation]}
          </span>
        </div>
      )}

      <div>
        <h4 className={styles.subhead}>Gemensamma förfäder</h4>
        {result.common_ancestors.length === 0 ? (
          <p className={`${styles.sentence} ${styles.muted}`}>
            Inga gemensamma förfäder inom 6 led.
          </p>
        ) : (
          <>
            <ul className={styles.ancestors} data-testid="common-ancestors">
              {ancestors.map((a) => (
                <li key={a.number}>
                  <AnimalName
                    number={a.number}
                    name={a.name}
                    fallback={a.number}
                  />{" "}
                  <span className={styles.muted}>
                    ({describeGenerations(a.generations)})
                  </span>
                </li>
              ))}
            </ul>
            {hidden > 0 && (
              <button
                type="button"
                className={styles.toggleLink}
                onClick={() => setShowAll(true)}
              >
                Visa {hidden} till
              </button>
            )}
          </>
        )}
      </div>

      <ul className={styles.facts}>
        <ParentFacts
          who="Hona"
          summary={femaleSummary}
          fallback="Oregistrerad hona"
        />
        <ParentFacts who="Hane" summary={result.male} fallback={maleFallback} />
      </ul>

      <div className={styles.cardFoot}>
        <button
          type="button"
          className="sb-btn sb-btn-secondary"
          aria-expanded={showTree}
          onClick={() => setShowTree((v) => !v)}
        >
          <SbIcon name="pedigree" size={16} />
          {showTree ? "Dölj släktträd" : "Visa släktträd"}
        </button>
        <a
          className={`sb-link ${styles.linkTarget}`}
          href={AVELSRAD_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          Avelsråd
        </a>
      </div>

      {showTree && (
        <div className={styles.treeBox} data-testid="result-tree">
          <TestbreedTree
            female={femaleSummary.pedigree}
            male={result.male.pedigree}
            highlight={highlight}
          />
        </div>
      )}
    </article>
  );
}
