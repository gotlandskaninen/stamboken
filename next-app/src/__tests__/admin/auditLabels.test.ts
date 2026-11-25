import { describe, it, expect } from "vitest";
import {
  fieldLabel,
  operationLabel,
  operationPhrase,
  rowTitle,
  tableLabel,
} from "@/app/(app)/stamboken/(dashboard)/admin/_lib/auditLabels";

describe("fieldLabel", () => {
  it("translates known columns", () => {
    expect(fieldLabel("fullname")).toBe("Fullständigt namn");
    expect(fieldLabel("v2_prod_access")).toBe("Riktiga stamboken");
    expect(fieldLabel("privileges")).toBe("Roller");
  });

  it("derives the *_privacy and *_id variants", () => {
    expect(fieldLabel("mobile_phone_privacy")).toBe("Mobiltelefon (synlighet)");
    expect(fieldLabel("origin_herd_id")).toBe("Ursprungsbesättning");
    expect(fieldLabel("disease_id")).toBe("Sjukdom");
    // weight_id saknas i FIELD_LABELS — träffar _id-strippningen.
    expect(fieldLabel("weight_id")).toBe("Vikt");
  });

  it("never returns a raw sensitive column name", () => {
    expect(fieldLabel("password_hash")).toBe("Lösenord (dolt)");
    expect(fieldLabel("auth_data")).toBe("Inloggningsuppgifter (dolda)");
  });

  it("falls back to the raw column name", () => {
    expect(fieldLabel("nagot_okant_falt")).toBe("nagot_okant_falt");
  });
});

describe("existing exports are unchanged (UserEditClient imports these)", () => {
  it("keeps operationLabel, tableLabel and rowTitle", () => {
    expect(operationLabel("UPDATE")).toBe("Ändrad");
    expect(tableLabel("bunny")).toBe("Ungar");
    expect(rowTitle("hbuser", "176")).toBe("Användare #176");
    expect(rowTitle("hbuser", "mass-logout-2026-08-21T10:00:00")).toBe(
      "Massutloggning — alla sessioner",
    );
    expect(rowTitle("audit_log", "purge-ip-20261114T034500Z")).toBe(
      "Gallring av IP-adresser",
    );
  });
});

describe("export rows (log_export)", () => {
  it("name the download, for the member exports too", () => {
    expect(operationLabel("READ")).toBe("Uttag");
    expect(operationPhrase("READ", "anna")).toBe("Hämtat av anna");
    expect(
      rowTitle(
        "individual",
        "export-avelsprioritet-2026-11-25T14:23:49.113774+00:00",
      ),
    ).toBe("Uttag: Avelsprioritet (CSV)");
    expect(
      rowTitle(
        "individual",
        "export-avelsprioritet-lista-2026-11-25T14:23:49.113774+00:00",
      ),
    ).toBe("Uttag: Avelsprioritet (listan på skärmen)");
    expect(
      rowTitle("membership", "export-matr-2026-11-25T08:00:00+00:00"),
    ).toBe("Uttag: matrikeln (MATR)");
    expect(
      rowTitle("membership", "export-address-list-2026-11-25T08:00:00+00:00"),
    ).toBe("Uttag: adresslistan till tryckeriet");
    expect(
      rowTitle("membership", "export-nytt-2026-11-25T08:00:00+00:00"),
    ).toBe("Uttag: nytt");
  });
});

describe("herd_tracking 999.5 columns", () => {
  it("labels the new columns and shows the buyer link only as an id", () => {
    expect(fieldLabel("kind")).toBe("Händelsetyp");
    expect(fieldLabel("operation_id")).toBe("Åtgärd");
    expect(fieldLabel("voided_reason")).toBe("Anledning till ångring");
    expect(fieldLabel("voided_by_user_id")).toBe("Ångrad av");
    expect(fieldLabel("voided_operation_id")).toBe("Ångrad i åtgärd");
    expect(fieldLabel("yearly_herd_report_id")).toBe("Årsrapport");
    expect(fieldLabel("transfer_id")).toBe("Försäljning");
    expect(fieldLabel("holder_contact_id")).toBe("Köparkontakt (id)");
  });
});
