"use client";

import { useState } from "react";
import { readModeCookieClient } from "@/lib/mode";
import {
  addressListUrl,
  koharenExportUrl,
  memberExportUrl,
} from "../statistik/exportUrl";

// Two call sites: the matrikel page and the statistik Masthead. On the
// matrikel page the buttons live inside the filter `<form method="get">`,
// where a native `<button>` defaults to type="submit" — that would navigate
// the filter form instead of (or racing with) the download. The explicit
// type="button" is load-bearing there and harmless in the
// Masthead, which has no form.
export function ExportButtons() {
  // Same demo/prod routing rule as the RTK baseQuery — see exportUrl.ts.
  const download = (url: string) => {
    window.location.href = url;
  };
  const [feeReminder, setFeeReminder] = useState(false);

  return (
    <>
      <button
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        onClick={() =>
          download(
            memberExportUrl(
              readModeCookieClient(),
              process.env.NEXT_PUBLIC_API_TEST_URL,
            ),
          )
        }
      >
        Exportera MATR
      </button>
      <button
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        onClick={() =>
          download(
            koharenExportUrl(
              readModeCookieClient(),
              process.env.NEXT_PUBLIC_API_TEST_URL,
            ),
          )
        }
      >
        Exportera Koharen
      </button>
      <button
        type="button"
        className="sb-btn sb-btn-secondary sb-btn-sm"
        onClick={() =>
          download(
            addressListUrl(
              readModeCookieClient(),
              process.env.NEXT_PUBLIC_API_TEST_URL,
              feeReminder,
            ),
          )
        }
      >
        Exportera adresslista
      </button>
      {/* No name: inside the matrikel filter form it must not join the query. */}
      <label>
        <input
          type="checkbox"
          checked={feeReminder}
          onChange={(e) => setFeeReminder(e.target.checked)}
        />{" "}
        Med Betala nu
      </label>
    </>
  );
}
