"use client";

import React, { useEffect, useRef } from "react";
import { Box } from "@mui/material";

import { loginWithGoogle } from "@/app/(app)/(auth)/actions";

declare global {
  interface Window {
    google: any;
  }
}

const FONT_BODY = "var(--font-ibm-plex-sans), 'IBM Plex Sans', sans-serif";

/** The official multi-colour Google "G". */
function GoogleG() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      aria-hidden
      focusable="false"
    >
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84Z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 7.3 9.14 5.38 12 5.38Z"
      />
    </svg>
  );
}

interface GoogleSignInButtonProps {
  returnTo?: string;
  /** Show the One Tap prompt ("Logga in som …") on load. */
  oneTap?: boolean;
  onError?: (message: string) => void;
}

/**
 * Custom-styled Google sign-in.
 *
 * Föreningen only allows Google accounts on the @gotlandskaninen.se domain, so
 * the visible label reads "Logga in med ditt föreningskonto (Google)". Google's
 * own rendered button can't carry custom text, so we render the real (working)
 * GIS button transparently ON TOP of the styled label: the user sees our
 * button, the click lands on Google's. The ID-token flow, the Flask POST and
 * the return_to redirect are all unchanged — presentation only.
 */
export default function GoogleSignInButton({
  returnTo,
  oneTap = true,
  onError,
}: GoogleSignInButtonProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    const handleCredentialResponse = async (response: any) => {
      try {
        const result = await loginWithGoogle(response.credential, returnTo);
        if (result?.error) onErrorRef.current?.(result.error);
        // On success, loginWithGoogle calls redirect() — nothing runs after.
      } catch (err: any) {
        if (err?.digest?.startsWith("NEXT_REDIRECT")) throw err;
        console.error("Google sign-in failed:", err);
      }
    };

    const init = () => {
      if (!window.google?.accounts?.id) return;

      const supportsFedCM =
        "IdentityCredential" in window && "get" in navigator.credentials;

      window.google.accounts.id.initialize({
        client_id: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
        auto_select: false,
        hd: "gotlandskaninen.se",
        use_fedcm_for_prompt: supportsFedCM,
        use_fedcm_for_button: supportsFedCM,
      });

      if (overlayRef.current) {
        overlayRef.current.innerHTML = "";
        // Match Google's (invisible) button to the visible label's width so the
        // whole custom button is clickable — including on narrow screens.
        const width = Math.min(
          400,
          Math.max(200, Math.round(overlayRef.current.offsetWidth || 380)),
        );
        window.google.accounts.id.renderButton(overlayRef.current, {
          theme: "outline",
          size: "large",
          type: "standard",
          shape: "rectangular",
          text: "signin_with",
          logo_alignment: "center",
          width,
        });
      }

      if (oneTap) {
        setTimeout(() => window.google.accounts.id.prompt(), 400);
      }
    };

    // Load Google Identity Services exactly once (shared across mounts).
    const SRC = "https://accounts.google.com/gsi/client";
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${SRC}"]`,
    );
    if (window.google?.accounts?.id) {
      init();
    } else if (existing) {
      existing.addEventListener("load", init, { once: true });
    } else {
      const script = document.createElement("script");
      script.src = SRC;
      script.async = true;
      script.defer = true;
      script.addEventListener("load", init, { once: true });
      document.head.appendChild(script);
    }
  }, [returnTo, oneTap]);

  return (
    <Box
      sx={{
        position: "relative",
        mt: "30px",
        "&:hover .gottis-visual": {
          bgcolor: "paper.2",
          borderColor: "ink.main",
        },
      }}
    >
      {/* Visible, design-matched label (not interactive — Google's button is on top) */}
      <Box
        className="gottis-visual"
        sx={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "10px",
          width: "100%",
          minHeight: 48,
          px: "18px",
          py: "12px",
          fontFamily: FONT_BODY,
          fontWeight: 500,
          fontSize: 15,
          color: "ink.main",
          bgcolor: "card",
          border: "1px solid",
          borderColor: "line.strong",
          borderRadius: "4px",
          transition:
            "background 200ms cubic-bezier(0.2,0.7,0.2,1), border-color 200ms cubic-bezier(0.2,0.7,0.2,1)",
          pointerEvents: "none",
          userSelect: "none",
        }}
      >
        <GoogleG />
        Logga in med ditt föreningskonto (Google)
      </Box>

      {/* The real Google button, transparent, capturing the clicks. */}
      <Box
        ref={overlayRef}
        aria-label="Logga in med ditt föreningskonto (Google)"
        sx={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: 0,
          "& iframe, & > div": { width: "100% !important" },
        }}
      />
    </Box>
  );
}
