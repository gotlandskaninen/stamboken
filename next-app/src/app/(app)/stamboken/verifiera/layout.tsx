import { ReactNode } from "react";
import Image from "next/image";
import { Source_Serif_4, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./verifiera.css";

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-source-serif",
  display: "swap",
});

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata = {
  title: "Verifiera Genbanksintyg — Stamboken",
  description: "Verifiera äktheten av ett digitalt genbanksintyg.",
};

// Public QR-code landing area — Stamboken design system, no dashboard chrome.
// Auth is skipped for /stamboken/verifiera/* via the middleware matcher.
export default function VerifieraLayout({ children }: { children: ReactNode }) {
  return (
    <div
      className={`vf-page ${sourceSerif.variable} ${plexSans.variable} ${plexMono.variable}`}
    >
      <header className="vf-head">
        <Image
          src="/stamboken/logo.png"
          alt="Föreningen Gotlandskaninen"
          width={34}
          height={34}
        />
        <div className="t">
          <strong>Föreningen Gotlandskaninen</strong>
          Stamboken · Verifiering
        </div>
      </header>
      {children}
    </div>
  );
}
