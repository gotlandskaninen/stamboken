"use client";

import { useState } from "react";
import { Card, CardContent, Typography } from "@mui/material";

/**
 * The masked copy of the paper certificate (docs/inkorg.md, Bilderna). The
 * image is same-origin and needs the session cookie; the API answers 403/404
 * when the user may not see it or none exists, and then the block is hidden.
 */
export function PaperCertificate({ number }: { number: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  const src = `/api/v2/individual/${encodeURIComponent(number)}/paper-certificate`;
  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Pappersintyg
        </Typography>
        <a href={src} target="_blank" rel="noopener noreferrer">
          {/* eslint-disable-next-line @next/next/no-img-element -- cookie-authed same-origin image, not for next/image */}
          <img
            src={src}
            alt="Pappersintyg, klicka för full storlek"
            onError={() => setFailed(true)}
            style={{ maxWidth: 240, maxHeight: 320, display: "block" }}
          />
        </a>
      </CardContent>
    </Card>
  );
}
