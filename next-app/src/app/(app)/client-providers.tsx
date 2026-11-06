"use client";
import { Provider } from "react-redux";
import { useTranslation } from "react-i18next";
import { AppRouterCacheProvider } from "@mui/material-nextjs/v16-appRouter";
import { ThemeProvider as MuiThemeProvider } from "@mui/material/styles";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import type { Locale } from "date-fns";
import { sv as svLocale } from "date-fns/locale";
import { enUS as enLocale } from "date-fns/locale";
import { de as deLocale } from "date-fns/locale";
import { store } from "@/redux/store";
import { createStambokenTheme } from "@/theme/stamboken";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { SnackbarProvider } from "@/components/SnackbarProvider";

// Global imports (must stay in client bundle)
import "@/i18n";

const dateFnsLocales: Record<string, Locale> = {
  sv: svLocale,
  en: enLocale,
  de: deLocale,
};

export function ClientProviders({ children }: { children: React.ReactNode }) {
  const { i18n } = useTranslation();
  return (
    <AppRouterCacheProvider>
      <Provider store={store}>
        <LocalizationProvider
          dateAdapter={AdapterDateFns}
          adapterLocale={dateFnsLocales[i18n.language] || svLocale}
        >
          <MuiThemeProvider theme={createStambokenTheme(i18n.language)}>
            <NotificationProvider>
              <SnackbarProvider>{children}</SnackbarProvider>
            </NotificationProvider>
          </MuiThemeProvider>
        </LocalizationProvider>
      </Provider>
    </AppRouterCacheProvider>
  );
}
