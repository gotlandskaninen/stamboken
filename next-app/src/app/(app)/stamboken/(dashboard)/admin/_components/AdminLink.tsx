"use client";

// Next 16's next/link is server-compatible (no "use client"), so passing
// Link via component={...} from a Server Component page is an unserializable
// function prop — the RSC render 500:ar on production builds. These wrappers
// keep the admin pages server-first (ADR-0008) while the component-prop
// composition happens on the client. Same pattern as public/LinkButton.
import Link from "next/link";
import { Button, type ButtonProps } from "@mui/material";

interface LinkButtonProps extends Omit<ButtonProps, "component" | "href"> {
  href: string;
}

export function LinkButton({ href, children, ...props }: LinkButtonProps) {
  const LinkBtn = Button as React.ComponentType<any>;
  return (
    <LinkBtn component={Link} href={href} {...props}>
      {children}
    </LinkBtn>
  );
}
