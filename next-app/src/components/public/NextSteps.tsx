import Link from "next/link";
import { Box, Typography } from "@mui/material";
import { LinkButton } from "@/components/public/LinkButton";
import { Icon, ICONS } from "@/components/public/Icons";

interface Step {
  label: string;
  href: string;
}

interface NextStepsContent {
  title: string;
  text: string;
  primary: Step;
  more: Step[];
}

const JOIN = {
  title: "Var med och bevara raserna",
  text: "Medlemskapet kostar 200 kr om året och gäller hela familjen.",
  primary: { label: "Bli medlem", href: "/bli-medlem" },
};

const BREED = {
  title: "Vill du föda upp inom genbanken?",
  text: "Genbanksbesättningarna är kärnan i bevarandet. Så här går det till att bli en av dem.",
  primary: { label: "Bli genbanksbesättning", href: "/bli-genbank" },
};

const GENBANK = { label: "Bli genbanksbesättning", href: "/bli-genbank" };
const GOTLAND = { label: "Gotlandskanin", href: "/gotlandskanin" };
const MELLERUD = { label: "Mellerudskanin", href: "/mellerudskanin" };

// Where a reader of each CMS page most likely wants to go next. A page that is
// not listed ends without the block.
const NEXT_STEPS: Record<string, NextStepsContent> = {
  foreningen: {
    ...JOIN,
    more: [GENBANK, { label: "Styrelse och kontakt", href: "/styrelsen" }],
  },
  styrelsen: {
    ...JOIN,
    more: [{ label: "Om föreningen", href: "/foreningen" }],
  },
  lantraskaninen: { ...JOIN, more: [GOTLAND, MELLERUD, GENBANK] },
  gotlandskanin: {
    ...JOIN,
    more: [
      { label: "Rasram för gotlandskanin", href: "/rasram-gotlandskanin" },
      GENBANK,
    ],
  },
  mellerudskanin: {
    ...JOIN,
    more: [
      { label: "Rasram för mellerudskanin", href: "/rasram-mellerudskanin" },
      GENBANK,
    ],
  },
  "rasram-gotlandskanin": {
    ...BREED,
    more: [
      { label: "Om gotlandskaninen", href: "/gotlandskanin" },
      { label: "Historik", href: "/historik" },
    ],
  },
  "rasram-mellerudskanin": {
    ...BREED,
    more: [
      { label: "Om mellerudskaninen", href: "/mellerudskanin" },
      { label: "Historik", href: "/historik" },
    ],
  },
  historik: {
    ...JOIN,
    more: [
      { label: "Föreningen i dag", href: "/foreningen" },
      GOTLAND,
      MELLERUD,
    ],
  },
  "bli-medlem": {
    title: "Redo att bli medlem?",
    text: "Fyll i ansökan, så hör vi av oss.",
    primary: { label: "Ansök om medlemskap", href: "/ansok" },
    more: [
      { label: "Om föreningen", href: "/foreningen" },
      { label: "Styrelse och kontakt", href: "/styrelsen" },
    ],
  },
};

export function NextSteps({ slug }: { slug: string }) {
  const content = NEXT_STEPS[slug];
  if (!content) return null;

  return (
    <Box
      component="aside"
      className="next-steps"
      aria-label="Nästa steg"
      sx={{
        mt: { xs: 8, md: 12 },
        bgcolor: "paper.2",
        border: 1,
        borderColor: "line.strong",
        borderRadius: "8px",
        p: { xs: 6, md: 9 },
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: "1fr auto" },
        gap: 6,
        alignItems: "center",
      }}
    >
      <Box>
        <Typography variant="h4" component="h2" sx={{ m: 0 }}>
          {content.title}
        </Typography>
        <Typography sx={{ mt: 2, color: "ink.2", maxWidth: 520 }}>
          {content.text}
        </Typography>
      </Box>
      <LinkButton
        href={content.primary.href}
        variant="contained"
        endIcon={<Icon d={ICONS.arrow} size={14} />}
      >
        {content.primary.label}
      </LinkButton>
      <Box
        sx={{
          gridColumn: "1 / -1",
          pt: 2,
          borderTop: 1,
          borderColor: "line.main",
          display: "flex",
          flexWrap: "wrap",
          columnGap: 8,
        }}
      >
        {content.more.map((step) => (
          <Link
            key={step.href}
            href={step.href}
            style={{ color: "inherit", textDecoration: "none" }}
          >
            <Typography
              component="span"
              sx={{
                display: "inline-block",
                py: 2,
                color: "ink.main",
                textDecoration: "underline",
                textDecorationColor: "line.strong",
                textUnderlineOffset: "3px",
              }}
            >
              {step.label} &rarr;
            </Typography>
          </Link>
        ))}
      </Box>
    </Box>
  );
}
