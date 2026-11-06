"use client";

import { useEffect, useState } from "react";
import { loginWithGoogle } from "@/app/(app)/(auth)/actions";

interface GoogleOneTapProps {
  showOnLoad?: boolean;
  prompt?: boolean;
  returnTo?: string;
}

export default function GoogleOneTap({
  showOnLoad = true,
  prompt = false,
  returnTo = "/stamboken/min-besattning",
}: GoogleOneTapProps) {
  const [, setIsLoggingIn] = useState(false);

  useEffect(() => {
    const handleCredentialResponse = async (response: any) => {
      setIsLoggingIn(true);
      try {
        const result = await loginWithGoogle(response.credential, returnTo);
        if (result?.error) {
          console.error("Google sign-in failed:", result.error);
          setIsLoggingIn(false);
        }
        // On success, loginWithGoogle calls redirect()
      } catch (error: any) {
        console.error("Google sign-in failed:", error);
        setIsLoggingIn(false);
      }
    };

    // Check for FedCM support (Chrome 117+)
    const supportsFedCM =
      typeof window !== "undefined" &&
      "IdentityCredential" in window &&
      "get" in navigator.credentials;

    // Load Google Identity Services script
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    document.head.appendChild(script);

    script.onload = () => {
      if (window.google) {
        window.google.accounts.id.initialize({
          client_id: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
          callback: handleCredentialResponse,
          auto_select: false,
          hd: "gotlandskaninen.se",
          use_fedcm_for_prompt: supportsFedCM,
          use_fedcm_for_button: supportsFedCM,
        });

        if (showOnLoad || prompt) {
          setTimeout(() => {
            window.google.accounts.id.prompt();
          }, 500);
        }
      }
    };

    return () => {
      if (script.parentNode) {
        document.head.removeChild(script);
      }
    };
  }, [showOnLoad, prompt, returnTo]);

  return null;
}
