import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import sv from "../messages/sv.json";
import en from "../messages/en.json";
import de from "../messages/de.json";

i18n.use(initReactI18next).init({
  resources: {
    sv: { translation: sv },
    en: { translation: en },
    de: { translation: de },
  },
  lng: "sv",
  fallbackLng: "sv",
  interpolation: {
    escapeValue: false,
  },
});
