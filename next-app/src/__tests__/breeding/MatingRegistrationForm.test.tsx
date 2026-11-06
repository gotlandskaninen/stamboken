import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { MatingRegistrationForm } from "@/components/herd/MatingRegistrationForm";

const theme = createTheme();

// Mock RTK Query hook used by IndividualAutocomplete
vi.mock("@/redux/api/apiSlice", async () => {
  const actual = await vi.importActual("@/redux/api/apiSlice");
  return {
    ...actual,
    useFetchIndividualsQuery: () => ({
      data: {
        items: [],
        total_count: 0,
        page: 1,
        per_page: 20,
        total_pages: 0,
      },
      isFetching: false,
    }),
  };
});

// Mock the i18n module
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        "breeding.mother": "Mor",
        "breeding.father": "Far",
        "breeding.matingDate": "Parningsdatum",
        "breeding.breedNotes": "Parningsanteckningar",
        "breeding.registerMating": "Registrera parning",
        "common.cancel": "Avbryt",
      };
      return translations[key] || key;
    },
  }),
}));

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

afterEach(() => {
  cleanup();
  localStorageMock.clear();
});

describe("MatingRegistrationForm", () => {
  it("renders all form fields", () => {
    renderWithTheme(
      <MatingRegistrationForm
        herdId="G1274"
        genebankId={1}
        onSubmit={vi.fn().mockResolvedValue(true)}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/^Mor/)).toBeDefined();
    expect(screen.getByLabelText(/^Far/)).toBeDefined();
    expect(screen.getByRole("group", { name: /Parningsdatum/i })).toBeDefined();
    expect(screen.getByLabelText(/Parningsanteckningar/i)).toBeDefined();
  });

  it("renders submit and cancel buttons", () => {
    renderWithTheme(
      <MatingRegistrationForm
        herdId="G1274"
        genebankId={1}
        onSubmit={vi.fn().mockResolvedValue(true)}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("Registrera parning")).toBeDefined();
    expect(screen.getByText("Avbryt")).toBeDefined();
  });

  it("calls onCancel when cancel button is clicked", () => {
    const onCancel = vi.fn();
    renderWithTheme(
      <MatingRegistrationForm
        herdId="G1274"
        genebankId={1}
        onSubmit={vi.fn().mockResolvedValue(true)}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByText("Avbryt"));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("disables submit when required fields are empty", () => {
    renderWithTheme(
      <MatingRegistrationForm
        herdId="G1274"
        genebankId={1}
        onSubmit={vi.fn().mockResolvedValue(true)}
        onCancel={vi.fn()}
      />,
    );

    const submitButton = screen.getByText("Registrera parning");
    expect(submitButton.closest("button")?.disabled).toBe(true);
  });

  it("shows loading state when isSubmitting is true", () => {
    renderWithTheme(
      <MatingRegistrationForm
        herdId="G1274"
        genebankId={1}
        onSubmit={vi.fn().mockResolvedValue(true)}
        onCancel={vi.fn()}
        isSubmitting={true}
      />,
    );

    expect(screen.getByRole("progressbar")).toBeDefined();
  });
});
