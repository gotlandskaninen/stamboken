"use client";

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
