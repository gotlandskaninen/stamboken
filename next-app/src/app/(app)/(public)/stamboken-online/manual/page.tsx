import { open, readFile } from "node:fs/promises";
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
const ROOT = path.join(process.cwd(), "public", DIR);

type Size = { width: number; height: number } | null;
type HastNode = { type: string; value?: string; children?: HastNode[] };

function textOf(node: HastNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(textOf).join("");
}

// Screenshot sizes from the PNG header, so the page reserves their space
// before they load. The files only change with a release; cache per process.
const sizes = new Map<string, Size>();

async function pngSize(name: string): Promise<Size> {
  if (sizes.has(name)) return sizes.get(name)!;
  let size: Size = null;
  try {
    const file = await open(path.join(ROOT, path.basename(name)));
    try {
      const { buffer } = await file.read(Buffer.alloc(24), 0, 24, 0);
      size = {
        width: buffer.readUInt32BE(16),
        height: buffer.readUInt32BE(20),
      };
    } finally {
      await file.close();
    }
  } catch {
    // a missing image renders without reserved space
  }
  sizes.set(name, size);
  return size;
}

// The manual's parts (its h2s) with the anchors the article renders, for the
// side menu on wide screens: same slugger, same heading order.
function parts(markdown: string) {
  const slug = headingSlugger();
  return [...markdown.matchAll(/^(#{1,4}) (.+)$/gm)]
    .map((m) => {
      const text = m[2].replace(/[*`]/g, "");
      return { level: m[1].length, text, id: slug(text) };
    })
    .filter((h) => h.level === 2 && h.id !== "innehåll");
}

function components(imageSizes: Map<string, Size>): Components {
  const slug = headingSlugger();
  const heading =
    (Tag: "h2" | "h3" | "h4") =>
    // eslint-disable-next-line react/display-name
    ({ node, children }: { node?: unknown; children?: ReactNode }) => (
      <Tag id={slug(textOf(node as HastNode))}>{children}</Tag>
    );
  return {
    // The page header carries the title; the h1 is still slugged so repeats
    // number the same way as on GitHub.
    h1: ({ node }) => {
      slug(textOf(node as HastNode));
      return null;
    },
    h2: heading("h2"),
    h3: heading("h3"),
    h4: heading("h4"),
    img: ({ src, alt }) => {
      const name = typeof src === "string" ? src : "";
      const size = imageSizes.get(name);
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={name ? DIR + name : undefined}
          alt={alt ?? ""}
          width={size?.width}
          height={size?.height}
          loading="lazy"
          decoding="async"
        />
      );
    },
    // The manual links to the site with its full address so the link also
    // works on GitHub; here it stays on whichever host serves the page.
    a: ({ href, children }) => (
      <a href={href?.replace(/^https:\/\/gotlandskaninen\.se(?=\/)/, "")}>
        {children}
      </a>
    ),
    // Wide tables scroll inside their box, not the page (ADR-0010). The box
    // takes focus so a keyboard can scroll it too.
    table: ({ children }) => (
      <div
        className="table-scroll"
        role="region"
        aria-label="Tabell, går att scrolla i sidled"
        tabIndex={0}
      >
        <table>{children}</table>
      </div>
    ),
  };
}

const LINK = {
  color: "ink.main",
  textDecorationColor: "var(--sb-line-strong)",
  textUnderlineOffset: "3px",
  "&:hover": { textDecorationColor: "var(--sb-lera)" },
} as const;

export default async function ManualPage() {
  const markdown = await readFile(path.join(ROOT, "USER_MANUAL.md"), "utf8");
  const names = [...markdown.matchAll(/!\[[^\]]*\]\(([^)]+\.png)\)/g)].map(
    (m) => m[1],
  );
  const imageSizes = new Map(
    await Promise.all(names.map(async (n) => [n, await pngSize(n)] as const)),
  );
  const toc = parts(markdown);

  return (
    <>
      <PageHeader
        section="Manual"
        parent={{ label: "Stamboken Online", href: "/stamboken-online" }}
        title="Manual för Stamboken"
        lede="Så använder du Stamboken: logga in, registrera kullar och kaniner, utfärda intyg, sälja och provpara."
      />
      <Box
        sx={{
          px: { xs: 6, md: 14 },
          py: { xs: 8, md: 12 },
          display: "grid",
          // Wide screens: the parts of the manual stay in reach beside the text.
          gridTemplateColumns: { lg: "minmax(0, 44rem) 15rem" },
          columnGap: 16,
          alignItems: "start",
        }}
      >
        <Box
          component="article"
          sx={{
            minWidth: 0,
            maxWidth: "44rem",
            lineHeight: 1.7,
            fontSize: { xs: "1rem", md: "1.0625rem" },
            textWrap: "pretty",
            overflowWrap: "anywhere",
            "& > :first-child": { mt: 0 },
            "& h2, & h3, & h4": {
              scrollMarginTop: "96px",
              textWrap: "balance",
            },
            "& h2": {
              mt: { xs: 12, md: 16 },
              mb: 5,
              pt: { xs: 8, md: 10 },
              borderTop: "1px solid var(--sb-line)",
              fontFamily: "var(--sb-display)",
              fontSize: { xs: "30px", md: "38px" },
              fontWeight: 400,
              lineHeight: 1.1,
              letterSpacing: "-0.015em",
            },
            "& h3": {
              mt: { xs: 9, md: 11 },
              mb: 3,
              fontFamily: "var(--sb-display)",
              fontSize: { xs: "23px", md: "26px" },
              fontWeight: 500,
              lineHeight: 1.2,
            },
            "& h4": {
              mt: 8,
              mb: 2,
              fontSize: "18px",
              fontWeight: 600,
              lineHeight: 1.3,
            },
            "& p, & ul, & ol": { my: 3 },
            "& li": { my: 1 },
            "& li > ul, & li > ol": { my: 1 },
            "& ul, & ol": { pl: 6 },
            "& strong": { fontWeight: 600 },
            "& a": LINK,
            "& img": {
              display: "block",
              maxWidth: "100%",
              height: "auto",
              my: 6,
              border: "1px solid var(--sb-line)",
              borderRadius: "6px",
              bgcolor: "paper.2",
            },
            "& blockquote": {
              m: 0,
              mb: 6,
              px: 5,
              py: 1,
              bgcolor: "paper.2",
              border: "1px solid var(--sb-line)",
              borderRadius: "6px",
              fontSize: "0.95em",
              color: "ink.2",
            },
            "& .table-scroll": {
              overflowX: "auto",
              my: 5,
              border: "1px solid var(--sb-line)",
              borderRadius: "6px",
            },
            "& table": {
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.92em",
              lineHeight: 1.5,
              overflowWrap: "normal",
            },
            "& th": { bgcolor: "paper.2", fontWeight: 600 },
            "& th, & td": {
              textAlign: "left",
              verticalAlign: "top",
              px: 3,
              py: 2.5,
              minWidth: "9rem",
              borderBottom: "1px solid var(--sb-line)",
            },
            "& tr:last-child td": { borderBottom: 0 },
            "& code": {
              fontFamily: "var(--sb-mono)",
              fontSize: "0.88em",
              px: 1,
              bgcolor: "paper.2",
              borderRadius: "3px",
            },
          }}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={components(imageSizes)}
            // The manual keeps its route markers for the coverage gate as HTML comments.
            skipHtml
          >
            {markdown}
          </ReactMarkdown>
        </Box>
        <Box
          component="nav"
          aria-labelledby="manual-parts"
          sx={{
            display: { xs: "none", lg: "block" },
            position: "sticky",
            top: "96px",
          }}
        >
          <Box
            component="h2"
            id="manual-parts"
            sx={{ m: 0, mb: 3, fontSize: "14px", fontWeight: 600 }}
          >
            Manualens delar
          </Box>
          <Box
            component="ul"
            sx={{
              listStyle: "none",
              m: 0,
              p: 0,
              borderLeft: "1px solid var(--sb-line)",
            }}
          >
            {toc.map((part) => (
              <li key={part.id}>
                <Box
                  component="a"
                  href={`#${part.id}`}
                  sx={{
                    display: "block",
                    py: 1.5,
                    pl: 4,
                    fontSize: "15px",
                    lineHeight: 1.4,
                    color: "ink.2",
                    textDecoration: "none",
                    "&:hover": {
                      color: "ink.main",
                      textDecoration: "underline",
                      textDecorationColor: "var(--sb-line-strong)",
                      textUnderlineOffset: "3px",
                    },
                  }}
                >
                  {part.text}
                </Box>
              </li>
            ))}
          </Box>
        </Box>
      </Box>
    </>
  );
}
