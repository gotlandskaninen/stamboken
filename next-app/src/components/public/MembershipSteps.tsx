import { Box, Typography } from "@mui/material";

export const MEMBERSHIP_PAYMENT =
  "Årsavgiften är 200 kr och betalas till Plusgiro 35 03 44-8 eller Swish 123 095 70 50. Ange namn och adress.";

const STEPS = [
  {
    title: "Fyll i ansökan",
    text: "Vi behöver din adress för att Koharen ska hitta fram.",
  },
  {
    title: "Betala årsavgiften",
    text: `${MEMBERSHIP_PAYMENT} Medlemskapet gäller hela familjen.`,
  },
  {
    title: "Vi hör av oss",
    text: "Föreningen kontaktar dig när ansökan har behandlats. Sedan kommer Koharen tre gånger om året.",
  },
];

export function MembershipSteps() {
  return (
    <Box
      component="aside"
      className="membership-steps"
      aria-labelledby="membership-steps-title"
      sx={{
        p: 7,
        bgcolor: "paper.2",
        border: 1,
        borderColor: "line.strong",
        borderRadius: "8px",
      }}
    >
      <Typography
        id="membership-steps-title"
        variant="h4"
        component="h2"
        sx={{ m: 0, fontWeight: 400 }}
      >
        Så blir du medlem
      </Typography>
      <Box component="ol" sx={{ m: 0, mt: 6, p: 0, listStyle: "none" }}>
        {STEPS.map((step, i) => {
          const last = i === STEPS.length - 1;
          return (
            <Box
              component="li"
              key={step.title}
              sx={{ position: "relative", pl: 11, pb: last ? 0 : 6 }}
            >
              <Typography
                variant="mono"
                aria-hidden="true"
                sx={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  width: 28,
                  height: 28,
                  display: "grid",
                  placeItems: "center",
                  border: "1px solid var(--sb-skog)",
                  borderRadius: "50%",
                  bgcolor: "paper.main",
                  fontSize: "13px",
                  color: "var(--sb-skog-deep)",
                }}
              >
                {i + 1}
              </Typography>
              {!last && (
                <Box
                  aria-hidden="true"
                  sx={{
                    position: "absolute",
                    left: 14,
                    top: 32,
                    bottom: 4,
                    width: "1px",
                    bgcolor: "line.strong",
                  }}
                />
              )}
              <Typography sx={{ fontWeight: 600, lineHeight: "28px" }}>
                {step.title}
              </Typography>
              <Typography
                sx={{
                  mt: 1,
                  color: "ink.2",
                  fontSize: "15px",
                  lineHeight: 1.55,
                }}
              >
                {step.text}
              </Typography>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
