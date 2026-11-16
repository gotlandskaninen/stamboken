"use client";

import { Card, CardContent, Typography } from "@mui/material";
import { useMode } from "@/lib/mode-context";

/**
 * The masked copy of the paper certificate (docs/inkorg.md, Bilderna). The
 * page renders this only when the API said a copy exists (individ/[number]/page.tsx).
 * The image needs the session cookie, and demo mode reads it from the demo API
 * as the rest of the page does.
 */
export function PaperCertificate({ number }: { number: string }) {
  const mode = useMode();
  const base =
    mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL
      : "/api";
  const src = `${base}/v2/individual/${encodeURIComponent(number)}/paper-certificate`;
  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Pappersintyg
        </Typography>
        <a href={src} target="_blank" rel="noopener noreferrer">
          {/* eslint-disable-next-line @next/next/no-img-element -- cookie-authed image, not for next/image */}
          <img
            src={src}
            alt="Pappersintyg, klicka för full storlek"
            style={{ maxWidth: 240, maxHeight: 320, display: "block" }}
          />
        </a>
      </CardContent>
    </Card>
  );
}
