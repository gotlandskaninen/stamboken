import { readFile } from "node:fs/promises";
import path from "node:path";
import type { ReactNode } from "react";
import { Box } from "@mui/material";
import type { Metadata } from "next";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/public/PageHeader";
import { headingSlugger } from "@/lib/headingSlug";

export const metadata: Metadata = {
  title: "Manual för Stamboken",
  description:
    "Så använder du Stamboken Online: logga in, registrera kullar och kaniner, utfärda intyg, sälja och provpara.",
};

// The manual and its screenshots live together in public/, so the page, the
// raw file on GitHub and the Docker image all read the same copy.
const DIR = "/stamboken/manual/";
const FILE = path.join(process.cwd(), "public", DIR, "USER_MANUAL.md");

type HastNode = { type: string; value?: string; children?: HastNode[] };

function textOf(node: HastNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(textOf).join("");
}

function components(): Components {
  const slug = headingSlugger();
  const heading =
    (Tag: "h2" | "h3" | "h4") =>
    // eslint-disable-next-line react/display-name
    ({ node, children }: { node?: unknown; children?: ReactNode }) => (
      <Tag id={slug(textOf(node as HastNode))}>{children}</Tag>
    );
  return {
    // The page header carries the title.
    h1: () => null,
    h2: heading("h2"),
    h3: heading("h3"),
    h4: heading("h4"),
    img: ({ src, alt }) => (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={typeof src === "string" ? DIR + src : undefined}
        alt={alt ?? ""}
        loading="lazy"
      />
    ),
    // Wide tables scroll inside their box, not the page (ADR-0010).
    table: ({ children }) => (
      <div className="table-scroll">
        <table>{children}</table>
      </div>
    ),
  };
}

export default async function ManualPage() {
  const markdown = await readFile(FILE, "utf8");
  return (
    <>
      <PageHeader
        section="Manual"
        parent={{ label: "Stamboken Online", href: "/stamboken-online" }}
        title="Manual för Stamboken"
        lede="Så använder du Stamboken: logga in, registrera kullar och kaniner, utfärda intyg, sälja och provpara."
      />
      <Box
        component="article"
        sx={{
          px: { xs: 6, md: 14 },
          py: { xs: 8, md: 12 },
          maxWidth: "52rem",
          lineHeight: 1.7,
          fontSize: { xs: "1rem", md: "1.05rem" },
          overflowWrap: "anywhere",
          "& h2": {
            mt: 12,
            pt: 6,
            borderTop: "1px solid var(--sb-line)",
            fontSize: { xs: "26px", md: "30px" },
            fontWeight: 400,
          },
          "& h3": { mt: 8, fontSize: { xs: "21px", md: "23px" } },
          "& h4": { mt: 6, fontSize: "18px" },
          "& h2, & h3, & h4": { scrollMarginTop: "80px" },
          "& a": { color: "primary.main" },
          "& img": {
            display: "block",
            maxWidth: "100%",
            height: "auto",
            my: 4,
            border: "1px solid var(--sb-line)",
            borderRadius: "6px",
          },
          "& blockquote": {
            m: 0,
            px: 5,
            py: 1,
            bgcolor: "paper.2",
            borderLeft: "3px solid var(--sb-line-strong)",
          },
          "& .table-scroll": { overflowX: "auto", my: 4 },
          "& table": { borderCollapse: "collapse", fontSize: "0.95em" },
          "& th, & td": {
            textAlign: "left",
            verticalAlign: "top",
            p: 2,
            borderBottom: "1px solid var(--sb-line)",
          },
          "& code": { fontSize: "0.9em" },
        }}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={components()}
          // The manual keeps its route markers for the coverage gate as HTML comments.
          skipHtml
        >
          {markdown}
        </ReactMarkdown>
      </Box>
    </>
  );
}
