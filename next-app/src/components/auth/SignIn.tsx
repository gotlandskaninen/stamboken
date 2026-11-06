"use client";

import React, { Suspense, useState } from "react";
import NextLink from "next/link";
import * as Yup from "yup";
import { Formik } from "formik";
import { useSearchParams } from "next/navigation";

import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Link,
  TextField,
  Typography,
} from "@mui/material";

import GoogleSignInButton from "@/components/auth/GoogleSignInButton";
import { loginWithPassword } from "@/app/(app)/(auth)/actions";

const FONT_BODY = "var(--font-ibm-plex-sans), 'IBM Plex Sans', sans-serif";
const FONT_MONO = "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace";

const fieldSx = {
  "& .MuiOutlinedInput-root": {
    bgcolor: "card",
    borderRadius: "4px",
    minHeight: 48,
    fontFamily: FONT_BODY,
    fontSize: 15,
    "& fieldset": { borderColor: "line.strong" },
    "&:hover fieldset": { borderColor: "line.strong" },
    "&.Mui-focused fieldset": { borderColor: "skog.main", borderWidth: "1px" },
    "&.Mui-focused": { boxShadow: "0 0 0 3px rgba(47,74,50,0.14)" },
  },
};

function FieldLabel({
  htmlFor,
  children,
}: {
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <Typography
      component="label"
      htmlFor={htmlFor}
      sx={{
        display: "block",
        fontFamily: FONT_BODY,
        fontSize: 13,
        fontWeight: 500,
        color: "ink.2",
        mb: "6px",
      }}
    >
      {children}
    </Typography>
  );
}

function SignIn() {
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("return_to") || undefined;
  const [error, setError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  return (
    <Box>
      <GoogleSignInButton returnTo={returnTo} onError={setError} />

      {/* Googles kontoväljare visar även privata konton (FedCM ignorerar
          hd-hinten), så säg upfront vilka konton som faktiskt släpps in. */}
      <Typography
        sx={{
          mt: "8px",
          fontFamily: FONT_BODY,
          fontSize: 12.5,
          color: "ink.3",
        }}
      >
        Har du ett föreningskonto (@gotlandskaninen.se)? Logga in med Google.
        Annars loggar du in med användarnamn och lösenord nedan. Utan tillgång
        till riktiga stamboken hamnar du i testmiljön.
      </Typography>

      {error && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}

      {/* eller */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          my: "26px",
          fontFamily: FONT_MONO,
          fontSize: 11,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "ink.3",
          "&::before, &::after": {
            content: '""',
            flex: 1,
            height: "1px",
            bgcolor: "line.main",
          },
        }}
      >
        eller
      </Box>

      <Formik
        initialValues={{
          username: "",
          password: "",
          remember: true,
        }}
        validationSchema={Yup.object().shape({
          username: Yup.string().required("Användarnamn krävs"),
          password: Yup.string().required("Lösenord krävs"),
        })}
        onSubmit={async (values) => {
          setError(null);
          setSubmitError(null);
          try {
            const result = await loginWithPassword(
              values.username,
              values.password,
              returnTo,
            );
            if (result?.error) {
              setSubmitError(result.error);
            }
            // On success, loginWithPassword calls redirect().
          } catch (err: any) {
            if (err?.digest?.startsWith("NEXT_REDIRECT")) throw err;
            setSubmitError(err.message || "Något gick fel");
          }
        }}
      >
        {({
          errors,
          handleBlur,
          handleChange,
          handleSubmit,
          isSubmitting,
          touched,
          values,
        }) => (
          <form noValidate onSubmit={handleSubmit}>
            {submitError && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                {submitError}
              </Alert>
            )}

            <Box sx={{ mb: "16px" }}>
              <FieldLabel htmlFor="username">Användarnamn</FieldLabel>
              <TextField
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                placeholder="ditt användarnamn"
                value={values.username}
                error={Boolean(touched.username && errors.username)}
                helperText={touched.username && errors.username}
                onBlur={handleBlur}
                onChange={handleChange}
                fullWidth
                sx={fieldSx}
              />
            </Box>

            <Box sx={{ mb: "8px" }}>
              <FieldLabel htmlFor="password">Lösenord</FieldLabel>
              <TextField
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={values.password}
                error={Boolean(touched.password && errors.password)}
                helperText={touched.password && errors.password}
                onBlur={handleBlur}
                onChange={handleChange}
                fullWidth
                sx={fieldSx}
              />
            </Box>

            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                mt: "-2px",
                mb: "22px",
              }}
            >
              <FormControlLabel
                control={
                  <Checkbox
                    name="remember"
                    checked={values.remember}
                    onChange={handleChange}
                    size="small"
                    sx={{
                      color: "skog.main",
                      "&.Mui-checked": { color: "skog.main" },
                    }}
                  />
                }
                label="Kom ihåg mig"
                sx={{
                  m: 0,
                  "& .MuiFormControlLabel-label": {
                    fontFamily: FONT_BODY,
                    fontSize: 13.5,
                    color: "ink.2",
                  },
                }}
              />
              <Typography
                sx={{
                  fontFamily: FONT_BODY,
                  fontSize: 13.5,
                  color: "ink.2",
                }}
              >
                Glömt lösenord? Kontakta{" "}
                <a href="mailto:admin@gotlandskaninen.se">administratören</a>.
              </Typography>
            </Box>

            <Button
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              disabled={isSubmitting}
              sx={{ minHeight: 50, fontSize: 16 }}
            >
              {isSubmitting ? "Loggar in…" : "Logga in"}
            </Button>
          </form>
        )}
      </Formik>

      <Typography
        sx={{
          mt: "28px",
          textAlign: "center",
          fontFamily: FONT_BODY,
          fontSize: 14,
          color: "ink.2",
        }}
      >
        Inte medlem än?{" "}
        <Link
          component={NextLink}
          href="/bli-medlem"
          sx={{
            color: "ink.main",
            fontWeight: 500,
            textDecorationColor: "lera.main",
          }}
        >
          Bli medlem →
        </Link>
      </Typography>

      <Box sx={{ mt: "40px", textAlign: "center" }}>
        <Link
          component={NextLink}
          href="/"
          underline="none"
          sx={{
            fontFamily: FONT_MONO,
            fontSize: 11,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "ink.3",
            "&:hover": { color: "ink.main" },
          }}
        >
          ← Tillbaka till gotlandskaninen.se
        </Link>
      </Box>
    </Box>
  );
}

function SignInWithSuspense() {
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}

export default SignInWithSuspense;
