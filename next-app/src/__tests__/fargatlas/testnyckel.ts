import type { Nyckel } from "@/lib/fargatlas/nyckel";

// A made-up key: the real one comes from the atlas package, and the operations repo checks it before each build
// (every number reachable, no loops, the known paths). Path to 22: Nej, then "Ja, testvilt".
export const TESTNYCKEL: Nyckel = {
  start: "q1",
  fragor: {
    q1: {
      text: "Testfråga ett?",
      hjalp: "Testhjälp ett.",
      svar: [
        { id: "q1-ja", text: "Ja", till: "q2" },
        { id: "q1-nej", text: "Nej", till: "q3" },
      ],
    },
    q2: {
      text: "Testfråga två?",
      svar: [
        { id: "q2-a", text: "Testsvar A", till: 12, hjalp: "Testhjälp A." },
        {
          id: "q2-b",
          text: "Testsvar B",
          till: 99,
          anteckning: "Testanteckning.",
        },
      ],
    },
    q3: {
      text: "Testfråga tre?",
      svar: [
        { id: "q3-ja", text: "Ja, testvilt", till: 22 },
        { id: "q3-nej", text: "Nej, testsvart", till: 11 },
      ],
    },
  },
  efter_numret: [
    {
      id: "rex",
      text: "Testfråga om pälsen?",
      ja: "Testsvar: välj Rex vid Päls.",
    },
  ],
  grupper: [{ id: "testgrupp", namn: "Testgrupp", nummer: [11, 12, 22, 99] }],
};
