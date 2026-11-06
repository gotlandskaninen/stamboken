"use client";

import { Box, Button, Paper, Typography } from "@mui/material";
import { logout } from "@/app/(app)/(auth)/actions";

/**
 * Friendly demo-lockout page (code review CR-02, user-approved copy).
 *
 * Rendered by the dashboard layout INSTEAD of the dashboard when the session is
 * valid in prod but the user row does not exist in herdbook_demo yet (account
 * created after the last nightly sync). The session/mode decision is made
 * server-side (requireDashboardSession, ADR-0008); this is a static client leaf
 * whose only interactivity is the logout button.
 */
export function DemoAccountMissing() {
  const handleSignOut = async () => {
    // Mirror AvatarMenu's logout flow: disable Google auto-select and
    // do a full reload so Google Identity Services state resets.
    if (typeof window !== "undefined" && window.google) {
      window.google.accounts.id.disableAutoSelect();
    }
    await logout();
    window.location.href = "/";
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 3,
      }}
    >
      <Paper sx={{ maxWidth: 520, p: 4, textAlign: "center" }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Ditt konto finns inte i testmiljön ännu
        </Typography>
        <Typography sx={{ mb: 3 }}>
          Testmiljön uppdateras varje natt med en kopia av riktiga stamboken.
          Ditt konto är nyare än senaste uppdateringen – välkommen tillbaka
          imorgon!
        </Typography>
        <Button variant="contained" onClick={handleSignOut}>
          Logga ut
        </Button>
      </Paper>
    </Box>
  );
}
