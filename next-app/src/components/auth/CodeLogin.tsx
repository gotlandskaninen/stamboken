"use client";

import {
  useEffect,
  useRef,
  useState,
  useTransition,
  type ReactNode,
} from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import "@/i18n";
import {
  type DisplayedRules,
  createMemberAccount,
  lookupLoginLink,
  redeemLoginLink,
  requestLoginCode,
  verifyLoginCode,
} from "@/app/(app)/(auth)/actions";
import styles from "./code-login.module.css";

export function CodeLoginForm({ returnTo }: { returnTo?: string }) {
  const { t } = useTranslation();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [switchFrom, setSwitchFrom] = useState<number>();
  const [pending, start] = useTransition();
  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        const fields = new FormData(event.currentTarget);
        setError("");
        start(async () => {
          if (!sent) {
            if (await requestLoginCode(String(fields.get("email")).trim()))
              setSent(true);
            else setError("unavailable");
          } else {
            const code = String(fields.get("code")).replace(/[\s-]/g, "");
            const result = await verifyLoginCode(code, returnTo, switchFrom);
            if ("error" in result) setError(result.error);
            if ("switchFrom" in result) setSwitchFrom(result.switchFrom);
          }
        });
      }}
    >
      {sent ? (
        <>
          <p role="status">{t("codeLogin.sent")}</p>
          <label htmlFor="login-code">{t("codeLogin.code")}</label>
          <input
            key="code"
            className="sb-input"
            id="login-code"
            name="code"
            type="text"
            autoComplete="one-time-code"
            inputMode="numeric"
            required
            placeholder="0000 0000"
            pattern="(?:[\s\-]*[0-9]){8}[\s\-]*"
            onChange={() => setSwitchFrom(undefined)}
          />
        </>
      ) : (
        <>
          <label htmlFor="login-email">{t("codeLogin.email")}</label>
          <input
            key="email"
            className="sb-input"
            id="login-email"
            name="email"
            autoComplete="email"
            type="email"
            required
          />
        </>
      )}
      {error && <p role="alert">{t(`codeLogin.${error}`)}</p>}
      {switchFrom !== undefined && (
        <p role="alert">{t("codeLogin.switchAccount")}</p>
      )}
      <button className="sb-btn" disabled={pending} type="submit">
        {t(
          switchFrom !== undefined
            ? "codeLogin.confirmSwitch"
            : sent
              ? "codeLogin.verify"
              : "codeLogin.send",
        )}
      </button>
      {sent && (
        <button
          className="sb-btn sb-btn-secondary"
          type="button"
          disabled={pending}
          onClick={() => {
            setSent(false);
            setSwitchFrom(undefined);
            setError("");
          }}
        >
          {t("codeLogin.newCode")}
        </button>
      )}
    </form>
  );
}

export function LoginLink({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation();
  const token = useRef("");
  const [target, setTarget] =
    useState<Awaited<ReturnType<typeof lookupLoginLink>>>();
  const [error, setError] = useState("");
  const [pending, start] = useTransition();
  useEffect(() => {
    const fragment = window.location.hash.slice(1);
    if (fragment) {
      token.current = fragment;
      // Passing null lets the App Router synchronize its canonical URL too.
      history.replaceState(null, "", location.pathname + location.search);
    }
    let active = true;
    if (enabled && token.current) {
      lookupLoginLink(token.current).then(
        (found) => {
          if (active) setTarget(found);
        },
        () => {
          if (active) setTarget(null);
        },
      );
    } else setTarget(null);
    return () => {
      active = false;
    };
  }, [enabled]);

  return (
    <main className={styles.page}>
      <h1>{t("codeLogin.linkTitle")}</h1>
      {!enabled || target === null || error ? (
        <p role="alert">{t(`codeLogin.${error || "invalidLink"}`)}</p>
      ) : target === undefined ? (
        <p role="status">{t("common.loading")}</p>
      ) : (
        <>
          <p>{t("codeLogin.linkFor", { name: target.name })}</p>
          {target.switchFrom !== null && (
            <p role="alert">{t("codeLogin.switchAccount")}</p>
          )}
          <button
            className="sb-btn"
            type="button"
            disabled={pending}
            onClick={() =>
              start(async () => {
                const result = await redeemLoginLink(
                  token.current,
                  target.switchFrom ?? undefined,
                );
                if ("switchFrom" in result)
                  setTarget({ ...target, switchFrom: result.switchFrom });
                if ("error" in result) setError(result.error);
              })
            }
          >
            {t(
              target.switchFrom === null
                ? "codeLogin.linkButton"
                : "codeLogin.confirmSwitch",
            )}
          </button>
        </>
      )}
      <p>
        <Link href="/auth/sign-in">{t("codeLogin.back")}</Link>
      </p>
    </main>
  );
}

// The next step for each error, so the member is never left without a way on.
const NEXT_STEP: Record<string, [href: string, label: string]> = {
  expired: ["sign-in", "codeLogin.newCode"],
  accountConflict: ["sign-in", "codeLogin.back"],
  rulesChanged: ["#kontoregler", "codeLogin.toRules"],
};

export function CreateAccount({
  rules,
  returnTo,
  children,
}: {
  rules?: DisplayedRules;
  returnTo?: string;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [acceptedHash, setAcceptedHash] = useState<string | null>(null);
  const accepted = !!rules && acceptedHash === rules.sha256;
  const [error, setError] = useState("");
  const [created, setCreated] = useState(false);
  const [pending, start] = useTransition();
  const checkbox = useRef<HTMLInputElement>(null);
  if (created)
    return (
      <main className={styles.page}>
        <h1>{t("codeLogin.created")}</h1>
        <p>{t("codeLogin.nextDay")}</p>
        <Link href="/stamboken/min-besattning">
          {t("codeLogin.toDashboard")}
        </Link>
      </main>
    );
  const next = NEXT_STEP[error];
  // Back to sign-in keeps where the member was going.
  const signIn = returnTo
    ? `/auth/sign-in?return_to=${encodeURIComponent(returnTo)}`
    : "/auth/sign-in";
  return (
    <main className={`${styles.page} ${styles.reading}`}>
      <p className={styles.back}>
        <Link href={signIn}>{t("codeLogin.back")}</Link>
      </p>
      <h1>{t("codeLogin.create")}</h1>
      <p className={styles.status}>{t("codeLogin.confirmed")}</p>
      <p>{t("codeLogin.accountPurpose")}</p>
      {rules ? (
        <>
          <p className={styles.lead}>
            {t("codeLogin.readFirst")}{" "}
            <a href="#godkann">{t("codeLogin.toAccept")}</a>
          </p>
          {children}
          <form
            id="godkann"
            className={`${styles.form} ${styles.accept}`}
            // The button stays usable, so a press without the tick explains itself.
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              if (!accepted) {
                setError("acceptFirst");
                checkbox.current?.focus();
                return;
              }
              setError("");
              start(async () => {
                const result = await createMemberAccount(
                  accepted,
                  rules,
                  returnTo,
                );
                if ("error" in result) {
                  setError(result.error);
                  if (result.error === "rulesChanged") setAcceptedHash(null);
                }
                if ("demoAccountCreated" in result) setCreated(true);
              });
            }}
          >
            <label className={styles.check}>
              <input
                ref={checkbox}
                type="checkbox"
                checked={accepted}
                required
                aria-describedby={error ? "godkann-fel" : undefined}
                onChange={(event) => {
                  setAcceptedHash(event.target.checked ? rules.sha256 : null);
                  if (error === "acceptFirst") setError("");
                }}
              />
              {t("codeLogin.accept")}
            </label>
            {error && (
              <p id="godkann-fel" role="alert" className={styles.alert}>
                {t(`codeLogin.${error}`)}
                {next && (
                  <>
                    {" "}
                    <Link href={next[0] === "sign-in" ? signIn : next[0]}>
                      {t(next[1])}
                    </Link>
                  </>
                )}
              </p>
            )}
            <button className="sb-btn" type="submit" disabled={pending}>
              {t("codeLogin.create")}
            </button>
          </form>
          <p>
            {t("codeLogin.rulesAgain")}{" "}
            <Link href="/kontoregler">{t("codeLogin.rules")}</Link>
          </p>
        </>
      ) : (
        <p role="alert" className={styles.alert}>
          {t("codeLogin.rulesMissing")}
        </p>
      )}
      <p>
        {t("codeLogin.privacyIntro")}{" "}
        <Link href="/dataskydd">{t("codeLogin.privacy")}</Link>
      </p>
    </main>
  );
}
