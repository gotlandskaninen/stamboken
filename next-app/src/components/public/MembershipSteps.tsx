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
    >
      <Typography
        id="membership-steps-title"
        variant="h4"
        component="h2"
        sx={{ m: 0, fontWeight: 400 }}
      >
        Så blir du medlem
      </Typography>
      <Box component="ol" sx={{ m: 0, mt: 5, p: 0, listStyle: "none" }}>
        {STEPS.map((step, i) => (
          <Box
            component="li"
            key={step.title}
            sx={{
              display: "grid",
              gridTemplateColumns: "28px 1fr",
              columnGap: 3,
              py: 4,
              borderTop: 1,
              borderColor: "line.main",
            }}
          >
            <Typography
              variant="mono"
              sx={{ pt: 0.5, color: "ink.2", fontSize: "13px" }}
            >
              {i + 1}
            </Typography>
            <Box>
              <Typography sx={{ fontWeight: 600 }}>{step.title}</Typography>
              <Typography sx={{ mt: 1, color: "ink.2", fontSize: "15px" }}>
                {step.text}
              </Typography>
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
