import { FetchBaseQueryError } from "@reduxjs/toolkit/query";

export interface ErrorDetails {
  timestamp: string;
  userAgent: string;
  url: string;
  userId: string;
  errorType: string;
  message: string;
  details: string;
  status?: number;
}

export function getErrorDetails(
  error: any,
  userId: string = "unknown",
): ErrorDetails {
  const timestamp = new Date().toISOString();
  const userAgent =
    typeof navigator !== "undefined" ? navigator.userAgent : "Server";
  const url = typeof window !== "undefined" ? window.location.href : "Unknown";

  // Enhanced error debugging - log the raw error structure (only in development)
  if (process.env.NODE_ENV === "development") {
    console.log("Raw error object:", {
      error,
      type: typeof error,
      constructor: error?.constructor?.name,
      keys: error ? Object.keys(error) : [],
      hasStatus: "status" in (error || {}),
      hasData: "data" in (error || {}),
      hasError: "error" in (error || {}),
      stringified: error ? JSON.stringify(error, null, 2) : "null/undefined",
    });
  }

  let errorInfo: ErrorDetails = {
    timestamp,
    userAgent,
    url,
    userId,
    errorType: "unknown",
    message: "Ett okänt fel uppstod",
    details: "",
  };

  // RTK Query error handling - try to safely access status
  let errorStatus: any;
  try {
    errorStatus = error?.status;
  } catch (e) {
    errorStatus = undefined;
  }

  if (errorStatus !== undefined) {
    errorInfo.status = errorStatus;
    errorInfo.errorType = `HTTP ${errorStatus}`;

    if (errorStatus === "FETCH_ERROR" || errorStatus === 0) {
      errorInfo.errorType = "Network Error";
      errorInfo.message =
        "Kan inte nå servern - kontrollera internetanslutningen";
      errorInfo.details =
        "API-servern svarar inte. Möjliga orsaker: Server nere, nätverksproblem, CORS-fel, eller felaktig URL";
    } else if (errorStatus === "TIMEOUT_ERROR") {
      errorInfo.errorType = "Timeout";
      errorInfo.message = "Förfrågan tog för lång tid";
      errorInfo.details =
        "Servern svarade inte inom 10 sekunder. Server kan vara överbelastad.";
    } else if (errorStatus === "PARSING_ERROR") {
      errorInfo.errorType = "Parse Error";
      errorInfo.message = "Serversvaret kunde inte tolkas";
      errorInfo.details = "API:t returnerade ogiltigt format (ej JSON)";
    } else if (errorStatus >= 500) {
      errorInfo.message = "Serverfel - försök igen senare";
      errorInfo.details = `HTTP ${errorStatus}: ${error.data?.message || "Intern serverfel"}`;
    } else if (errorStatus === 403) {
      errorInfo.message = "Åtkomst nekad - inte behörig";
      errorInfo.details =
        "Användaren har inte rätt att utföra denna operation eller sessionen har gått ut";
    } else if (errorStatus === 404) {
      errorInfo.message = "Resursen hittades inte";
      errorInfo.details = "API-endpoint eller resursen finns inte";
    } else if (errorStatus === 401) {
      errorInfo.message = "Du måste logga in igen";
      errorInfo.details = "Sessionen har gått ut eller är ogiltig";
    } else if (errorStatus >= 400) {
      errorInfo.message = "Felaktig förfrågan";
      errorInfo.details = `HTTP ${errorStatus}: ${error.data?.message || "Klientfel"}`;
    }
  } else if (
    error?.name === "AbortError" ||
    error?.message?.includes("timeout")
  ) {
    errorInfo.errorType = "Timeout";
    errorInfo.message = "Förfrågan tog för lång tid";
    errorInfo.details = "Servern svarade inte inom angiven tid.";
  } else if (error?.message) {
    errorInfo.details = error.message;
    errorInfo.message = "Ett tekniskt fel uppstod";
  } else if (error && typeof error === "object") {
    // Handle empty objects or objects with no recognizable structure
    const errorString = JSON.stringify(error);
    if (errorString === "{}") {
      errorInfo.errorType = "Empty Error Object";
      errorInfo.message = "Ett tomt felobjekt mottogs från servern";
      errorInfo.details =
        "API:t returnerade ett tomt felobjekt. Detta kan indikera ett problem med serverns felhantering.";
    } else {
      errorInfo.details = `Okänt felformat: ${errorString}`;
      errorInfo.message = "Ett oväntat fel uppstod";
    }
  } else if (error === null || error === undefined) {
    errorInfo.errorType = "Null/Undefined Error";
    errorInfo.message = "Ett null eller undefined fel mottogs";
    errorInfo.details =
      "API:t returnerade null eller undefined som fel. Detta indikerar ett problem med serverns felhantering.";
  }

  return errorInfo;
}

export function formatErrorForAdmin(errorDetails: ErrorDetails): string {
  return `Felrapport - Stamboken Online

Fel uppstod: ${errorDetails.message}
Tid: ${errorDetails.timestamp}
Användare: ${errorDetails.userId}
Feltyp: ${errorDetails.errorType}
Status: ${errorDetails.status || "N/A"}
Detaljer: ${errorDetails.details}

Teknisk info:
URL: ${errorDetails.url}
User Agent: ${errorDetails.userAgent}

JSON för utvecklare:
${JSON.stringify(errorDetails, null, 2)}`;
}

export function getUserFriendlyMessage(error: any): string {
  const details = getErrorDetails(error);
  return details.message;
}
