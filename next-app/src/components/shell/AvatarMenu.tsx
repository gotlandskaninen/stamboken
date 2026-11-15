"use client";

import React from "react";
import { useRouter } from "next/navigation";
import {
  Avatar,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  Menu,
  MenuItem,
  Tooltip,
} from "@mui/material";
import AccountCircleIcon from "@mui/icons-material/AccountCircle";
import { useUser } from "@/lib/user-context";
import {
  hasAnyVisible,
  isMemberAdmin,
} from "@/app/(app)/stamboken/(dashboard)/admin/_components/navConfig";
import { useMode } from "@/lib/mode-context";
import { logout, setMode } from "@/app/(app)/(auth)/actions";
import { apiSlice } from "@/redux/api/apiSlice";
import { usePendingMemberApplicationCountQuery } from "@/redux/api/memberApplicationsEndpoints";
import { useAppDispatch } from "@/hooks/useAppDispatch";

export function AvatarMenu({ unread = 0 }: { unread?: number }) {
  const [anchor, setAnchor] = React.useState<null | HTMLElement>(null);
  const [modeDialogOpen, setModeDialogOpen] = React.useState(false);
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useUser();
  const mode = useMode();

  // Same gate as the deleted template sidebar's medlem section had.
  // Samma predikat som adminpanelens Medlemsregister-kort och layout-gate.
  const canSeeMemberAdmin = user ? isMemberAdmin(user) : false;
  const { data: pendingData } = usePendingMemberApplicationCountQuery(
    undefined,
    {
      pollingInterval: 30_000,
      skip: !canSeeMemberAdmin,
    },
  );
  const pendingCount = pendingData?.pending ?? 0;

  const displayName =
    user?.google_name ||
    user?.fullname ||
    user?.username ||
    user?.email ||
    "User";
  const initials = displayName
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const profilePicture =
    (user?.use_google_picture && user?.google_picture) ||
    (user?.profile_picture
      ? `/uppladdningar/profiler/${user.profile_picture}`
      : null);

  const closeMenu = () => setAnchor(null);
  const switchingToDemo = mode === "prod";

  const handleModeConfirm = async () => {
    setModeDialogOpen(false);
    await setMode(switchingToDemo ? "demo" : "prod");
    // CR-01: RTK cache keys don't include mode; purge so refetches read the new
    // sb_mode cookie instead of the other backend's cached rows.
    dispatch(apiSlice.util.resetApiState());
    router.refresh();
  };

  const handleSignOut = async () => {
    if (typeof window !== "undefined" && window.google) {
      window.google.accounts.id.disableAutoSelect();
    }
    await logout();
    window.location.href = "/";
  };

  return (
    <>
      <Tooltip title="Account">
        <IconButton
          aria-label="Account"
          aria-haspopup="true"
          onClick={(e) => setAnchor(e.currentTarget)}
          size="small"
        >
          {profilePicture ? (
            <Avatar
              src={profilePicture}
              alt={displayName}
              sx={{ width: 32, height: 32 }}
            />
          ) : initials ? (
            <Avatar
              sx={{
                width: 32,
                height: 32,
                bgcolor: "var(--sb-skog)",
                color: "#fff",
                fontFamily: "var(--sb-mono)",
                fontSize: 13,
              }}
            >
              {initials}
            </Avatar>
          ) : (
            <AccountCircleIcon />
          )}
        </IconButton>
      </Tooltip>
      <Menu
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={closeMenu}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        keepMounted
      >
        <MenuItem disabled>{displayName}</MenuItem>
        {user?.google_email && user.google_email !== user.email && (
          <MenuItem disabled sx={{ fontSize: "0.875rem", opacity: 0.7 }}>
            {user.google_email}
          </MenuItem>
        )}
        <Divider />
        <MenuItem
          onClick={() => {
            closeMenu();
            router.push("/stamboken/profil");
          }}
        >
          Profil
        </MenuItem>
        <MenuItem
          onClick={() => {
            closeMenu();
            router.push("/stamboken/notiser");
          }}
        >
          {unread > 0 ? `Notiser (${unread})` : "Notiser"}
        </MenuItem>
        {user && hasAnyVisible(user) && (
          <MenuItem
            onClick={() => {
              closeMenu();
              router.push("/stamboken/admin");
            }}
          >
            Adminpanel
          </MenuItem>
        )}
        {/* Array (not Fragment) children: MUI Menu walks direct children for
            focus/keyboard nav and rejects Fragments (WR-03, ported pattern). */}
        {canSeeMemberAdmin && [
          <Divider key="medlem-divider" />,
          <MenuItem
            key="medlem-ansokningar"
            onClick={() => {
              closeMenu();
              router.push("/medlem/ansokningar");
            }}
          >
            {pendingCount > 0
              ? `Medlemsansökningar (${pendingCount})`
              : "Medlemsansökningar"}
          </MenuItem>,
          <MenuItem
            key="medlem-matrikel"
            onClick={() => {
              closeMenu();
              router.push("/medlem/matrikel");
            }}
          >
            Matrikel
          </MenuItem>,
          <MenuItem
            key="medlem-statistik"
            onClick={() => {
              closeMenu();
              router.push("/medlem/statistik");
            }}
          >
            Statistik
          </MenuItem>,
        ]}
        {user?.v2_prod_access && [
          <Divider key="mode-divider" />,
          <MenuItem
            key="mode-toggle"
            onClick={() => {
              closeMenu();
              setModeDialogOpen(true);
            }}
          >
            {switchingToDemo
              ? "Byt till testmiljön"
              : "Byt till riktiga stamboken"}
          </MenuItem>,
        ]}
        <Divider />
        <MenuItem onClick={handleSignOut}>Logga ut</MenuItem>
      </Menu>
      <Dialog
        open={modeDialogOpen}
        onClose={() => setModeDialogOpen(false)}
        aria-labelledby="mode-dialog-title"
      >
        <DialogTitle id="mode-dialog-title">
          {switchingToDemo
            ? "Byta till testmiljön?"
            : "Byta till riktiga stamboken?"}
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            {switchingToDemo
              ? "Du är på väg att byta till testmiljön. Där kan du prova, ändra och testa precis hur mycket du vill — inget du gör där påverkar riktiga stamboken. Varje natt skrivs testmiljön över med en färsk kopia av riktiga stambokens uppgifter, så ändringar du gör där försvinner."
              : "Du är på väg att byta till riktiga stamboken. Ändringar du gör där sparas på riktigt och syns för alla. Det mesta går att rätta i efterhand — och genbanksansvarig kan hjälpa dig att rätta till det om något blir fel."}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setModeDialogOpen(false)} variant="outlined">
            Avbryt
          </Button>
          <Button onClick={handleModeConfirm} variant="contained" autoFocus>
            {switchingToDemo
              ? "Ja, byt till testmiljön"
              : "Ja, byt till riktiga stamboken"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
