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
        mt: 14,
        bgcolor: "paper.2",
        border: 1,
        borderColor: "line.strong",
        borderRadius: "8px",
        display: "grid",
        gridTemplateColumns: {
          xs: "1fr",
          sm: "minmax(0, 1.15fr) minmax(0, 1fr)",
        },
      }}
    >
      <Box sx={{ p: { xs: 6, sm: 9 } }}>
        <Typography variant="h4" component="h2" sx={{ m: 0, fontWeight: 400 }}>
          {content.title}
        </Typography>
        <Typography sx={{ mt: 2.5, mb: 6, color: "ink.2", maxWidth: "40ch" }}>
          {content.text}
        </Typography>
        <LinkButton
          href={content.primary.href}
          variant="contained"
          endIcon={<Icon d={ICONS.arrow} size={14} />}
        >
          {content.primary.label}
        </LinkButton>
      </Box>
      <Box
        component="ul"
        sx={{
          m: 0,
          px: { xs: 6, sm: 9 },
          py: { xs: 2, sm: 5 },
          listStyle: "none",
          // Full shorthands: a responsive `borderLeft: 1` lands after
          // `borderColor` in the CSS and resets the colour to the text colour.
          borderLeft: { sm: "1px solid var(--sb-line-strong)" },
          borderTop: { xs: "1px solid var(--sb-line-strong)", sm: "none" },
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        {content.more.map((step, i) => (
          <Box
            component="li"
            key={step.href}
            sx={{ borderTop: i ? 1 : 0, borderColor: "line.main" }}
          >
            <Link
              href={step.href}
              style={{ color: "inherit", textDecoration: "none" }}
            >
              <Typography
                component="span"
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  gap: 4,
                  py: 3.5,
                  fontWeight: 500,
                  "&:hover": {
                    textDecoration: "underline",
                    textUnderlineOffset: "3px",
                  },
                }}
              >
                <span>{step.label}</span>
                <span aria-hidden="true">&rarr;</span>
              </Typography>
            </Link>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
