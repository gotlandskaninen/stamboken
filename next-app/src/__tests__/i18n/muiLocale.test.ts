import { describe, it, expect } from "vitest";
import { createStambokenTheme, stambokenTheme } from "@/theme/stamboken";

type LocaleText = {
  cancelButtonLabel?: string;
  columnMenuSortAsc?: string;
};

type LocalizedThemeComponents = {
  MuiDataGrid?: {
    defaultProps?: {
      localeText?: LocaleText;
    };
  };
  MuiLocalizationProvider?: {
    defaultProps?: {
      localeText?: LocaleText;
    };
  };
  MuiTablePagination?: {
    defaultProps?: {
      labelRowsPerPage?: string;
    };
  };
};

function componentsFor(locale: string): LocalizedThemeComponents | undefined {
  return createStambokenTheme(locale).components as unknown as
    | LocalizedThemeComponents
    | undefined;
}

function dgSortAsc(locale: string): string | undefined {
  return componentsFor(locale)?.MuiDataGrid?.defaultProps?.localeText
    ?.columnMenuSortAsc;
}

function datePickerCancel(locale: string): string | undefined {
  return componentsFor(locale)?.MuiLocalizationProvider?.defaultProps
    ?.localeText?.cancelButtonLabel;
}

function tableRowsPerPage(locale: string): string | undefined {
  return componentsFor(locale)?.MuiTablePagination?.defaultProps
    ?.labelRowsPerPage;
}

describe("createStambokenTheme — MUI locale integration", () => {
  it("returns a usable theme and defaults all MUI packs to Swedish", () => {
    expect(createStambokenTheme()).toBeDefined();
    expect(dgSortAsc("sv")).toBe("Sortera stigande");
    expect(datePickerCancel("sv")).toBe("Avbryt");
    expect(tableRowsPerPage("sv")).toBe("Rader per sida:");
  });

  it("merges the Swedish MUI core locale", () => {
    expect(tableRowsPerPage("sv")).toBe("Rader per sida:");
  });

  it("merges DISTINCT per-language DataGrid locale strings", () => {
    expect(dgSortAsc("sv")).toBe("Sortera stigande");
    expect(dgSortAsc("en")).toBe("Sort by ASC");
    expect(dgSortAsc("de")).toBe("Sortiere aufsteigend");

    const all = [dgSortAsc("sv"), dgSortAsc("en"), dgSortAsc("de")];
    expect(new Set(all).size).toBe(3);
  });

  it("merges DISTINCT per-language DatePicker locale strings", () => {
    expect(datePickerCancel("sv")).toBe("Avbryt");
    expect(datePickerCancel("en")).toBe("Cancel");
    expect(datePickerCancel("de")).toBe("Abbrechen");

    const all = [
      datePickerCancel("sv"),
      datePickerCancel("en"),
      datePickerCancel("de"),
    ];
    expect(new Set(all).size).toBe(3);
  });

  it("falls back to Swedish for an unknown locale", () => {
    expect(dgSortAsc("fr")).toBe("Sortera stigande");
    expect(datePickerCancel("fr")).toBe("Avbryt");
    expect(tableRowsPerPage("fr")).toBe("Rader per sida:");
  });

  it("keeps the base stambokenTheme export free of locale packs", () => {
    const components = stambokenTheme.components as unknown as
      | LocalizedThemeComponents
      | undefined;

    expect(stambokenTheme).toBeDefined();
    expect(components?.MuiDataGrid?.defaultProps?.localeText).toBeUndefined();
    expect(components?.MuiLocalizationProvider).toBeUndefined();
    expect(components?.MuiTablePagination).toBeUndefined();
  });
});
