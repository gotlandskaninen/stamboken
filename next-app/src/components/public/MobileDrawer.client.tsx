"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Box,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
} from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";

interface NavLink {
  label: string;
  href: string;
  children?: { label: string; href: string }[];
}

interface MobileDrawerProps {
  links: NavLink[];
  /** Primary action shown at the top of the drawer — mirrors the desktop
   *  Stamboken button, which is hidden below md. */
  cta?: { label: string; href: string };
}

export function MobileDrawer({ links, cta }: MobileDrawerProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <IconButton
        aria-label="Meny"
        onClick={() => setOpen(true)}
        sx={{ display: { xs: "flex", md: "none" }, color: "ink.main" }}
      >
        <Box
          component="svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.6}
          strokeLinecap="round"
          sx={{
            width: 22,
            height: 22,
          }}
        >
          <path d="M3 6h18" />
          <path d="M3 12h18" />
          <path d="M3 18h18" />
        </Box>
      </IconButton>

      <Drawer
        anchor="right"
        open={open}
        onClose={() => setOpen(false)}
        slotProps={{
          paper: {
            sx: {
              width: 300,
              bgcolor: "paper.main",
            },
          },
        }}
      >
        <Box
          sx={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            p: 4,
            borderBottom: 1,
            borderColor: "line.main",
          }}
        >
          <Typography sx={{ fontWeight: 600 }}>Meny</Typography>
          <IconButton onClick={() => setOpen(false)} sx={{ color: "ink.main" }}>
            <Box
              component="svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              sx={{
                width: 20,
                height: 20,
              }}
            >
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </Box>
          </IconButton>
        </Box>

        {cta && (
          <Box sx={{ px: 4, pt: 4 }}>
            <LinkButton
              href={cta.href}
              variant="contained"
              fullWidth
              onClick={() => setOpen(false)}
            >
              {cta.label}
            </LinkButton>
          </Box>
        )}

        <List sx={{ px: 2 }}>
          {links.map((link) => (
            <Box key={link.href}>
              <ListItem disablePadding>
                <ListItemButton
                  component={Link}
                  href={link.href}
                  onClick={() => setOpen(false)}
                  sx={{ borderRadius: "4px" }}
                >
                  <ListItemText
                    primary={link.label}
                    slotProps={{
                      primary: { sx: { fontWeight: 500 } },
                    }}
                  />
                </ListItemButton>
              </ListItem>
              {link.children?.map((child) => (
                <ListItem key={child.href} disablePadding sx={{ pl: 4 }}>
                  <ListItemButton
                    component={Link}
                    href={child.href}
                    onClick={() => setOpen(false)}
                    sx={{ borderRadius: "4px" }}
                  >
                    <ListItemText
                      primary={child.label}
                      slotProps={{
                        primary: {
                          sx: { fontSize: "14px", color: "ink.2" },
                        },
                      }}
                    />
                  </ListItemButton>
                </ListItem>
              ))}
            </Box>
          ))}
        </List>
      </Drawer>
    </>
  );
}
