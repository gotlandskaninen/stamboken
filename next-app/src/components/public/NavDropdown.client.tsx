"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Box, Typography } from "@mui/material";

interface DropdownItem {
  label: string;
  href: string;
  subtitle?: string;
  image?: string;
}

interface NavDropdownProps {
  label: string;
  href: string;
  items: DropdownItem[];
  active?: boolean;
}

export function NavDropdown({
  label,
  href,
  items,
  active: activeProp,
}: NavDropdownProps) {
  const pathname = usePathname();
  const active =
    activeProp ?? (pathname === href || items.some((i) => i.href === pathname));
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open, close]);

  // Children with a thumbnail (the two breeds) keep the picture-card look;
  // text-only children (e.g. "Bli genbanksbesättning") would otherwise sit with their
  // label under the thumbnails' baseline, so they render as a compact text
  // group below the cards instead.
  const cardItems = items.filter((i) => i.image);
  const textItems = items.filter((i) => !i.image);

  return (
    <Box ref={ref} sx={{ position: "relative" }}>
      <Box
        component="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="true"
        sx={{
          background: "none",
          border: "none",
          cursor: "pointer",
          fontFamily: "'IBM Plex Sans', sans-serif",
          fontSize: "13.5px",
          color: active ? "ink.main" : "ink.2",
          fontWeight: active ? 600 : 400,
          borderBottom: active ? "2px solid" : "2px solid transparent",
          borderColor: active ? "lera.main" : "transparent",
          pb: "2px",
          display: "inline-flex",
          alignItems: "center",
          gap: 1,
          minHeight: "44px",
          px: 0,
          "&:hover": { color: "ink.main" },
        }}
      >
        {label}
        <Box
          component="svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          sx={{
            width: 12,
            height: 12,
            transition: "transform 200ms cubic-bezier(0.2, 0.7, 0.2, 1)",
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
          }}
        >
          <path d="m6 9 6 6 6-6" />
        </Box>
      </Box>

      {open && (
        <Box
          sx={{
            position: "absolute",
            top: "calc(100% + 10px)",
            left: "50%",
            transform: "translateX(-50%)",
            bgcolor: "card",
            border: 1,
            borderColor: "line.main",
            borderRadius: "8px",
            boxShadow: 3,
            minWidth: 260,
            zIndex: 100,
            overflow: "hidden",
          }}
        >
          {cardItems.map((item) => (
            <Box
              key={item.href}
              component={Link}
              href={item.href}
              onClick={close}
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 3,
                px: 4,
                py: 3,
                textDecoration: "none",
                color: "inherit",
                "&:hover": { bgcolor: "paper.2" },
              }}
            >
              <Box
                component="img"
                src={item.image}
                alt=""
                sx={{
                  width: 44,
                  height: 44,
                  borderRadius: "4px",
                  objectFit: "cover",
                  border: 1,
                  borderColor: "line.faint",
                  flexShrink: 0,
                }}
              />
              <Box>
                <Typography sx={{ fontSize: "14px", fontWeight: 600 }}>
                  {item.label}
                </Typography>
                {item.subtitle && (
                  <Typography variant="mono" sx={{ mt: 0.5 }}>
                    {item.subtitle}
                  </Typography>
                )}
              </Box>
            </Box>
          ))}
          {textItems.map((item, i) => (
            <Box
              key={item.href}
              component={Link}
              href={item.href}
              onClick={close}
              sx={{
                display: "block",
                px: 4,
                py: 2.5,
                textDecoration: "none",
                color: "inherit",
                ...(i === 0 &&
                  cardItems.length > 0 && {
                    borderTop: 1,
                    borderColor: "line.faint",
                  }),
                "&:hover": { bgcolor: "paper.2" },
              }}
            >
              <Typography sx={{ fontSize: "14px", fontWeight: 600 }}>
                {item.label}
              </Typography>
              {item.subtitle && (
                <Typography variant="mono" sx={{ mt: 0.5 }}>
                  {item.subtitle}
                </Typography>
              )}
            </Box>
          ))}
          <Box
            component={Link}
            href={href}
            onClick={close}
            sx={{
              display: "block",
              px: 4,
              py: 2.5,
              textDecoration: "none",
              color: "inherit",
              "&:hover": { bgcolor: "paper.2" },
            }}
          >
            <Typography sx={{ fontSize: "14px", fontWeight: 600 }}>
              Om lantraskaninen
            </Typography>
            <Typography variant="mono" sx={{ mt: 0.5 }}>
              vad en lantras är
            </Typography>
          </Box>
        </Box>
      )}
    </Box>
  );
}
