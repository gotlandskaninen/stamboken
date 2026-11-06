"use client";

import { readModeCookieClient } from "@/lib/mode";
import { koharenExportUrl, memberExportUrl } from "../statistik/exportUrl";

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
    </>
  );
}
