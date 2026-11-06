import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LanguageToggle } from "@/components/shell/LanguageToggle";

const changeLanguage = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", async () => {
  const React = await import("react");

  return {
    useTranslation: () => {
      const [language, setLanguage] = React.useState("sv");

      return {
        i18n: {
          language,
          changeLanguage: (nextLanguage: string) => {
            changeLanguage(nextLanguage);
            setLanguage(nextLanguage);
          },
        },
      };
    },
  };
});

afterEach(() => {
  vi.clearAllMocks();
  cleanup();
});

describe("LanguageToggle", () => {
  it("shows SV by default and switches to EN when clicked", () => {
    render(<LanguageToggle />);

    expect(screen.getByText("SV")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Byt språk till engelska" }),
    );

    expect(changeLanguage).toHaveBeenCalledWith("en");
    expect(screen.getByText("EN")).toBeInTheDocument();
  });

  it("offers only an SV and EN language control", () => {
    render(<LanguageToggle />);

    expect(screen.queryByText("Deutsch")).toBeNull();
    expect(screen.queryByText("DE")).toBeNull();
  });
});
