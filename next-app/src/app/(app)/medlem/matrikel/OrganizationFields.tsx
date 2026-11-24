import { useId } from "react";
import { Checkbox, FormControlLabel } from "@mui/material";
import ds from "@/styles/ds-admin.module.css";
import type { Organization } from "./types";

type OrganizationForm = { enabled: boolean; name: string; number?: string };

export function organizationForm(membership: Organization): OrganizationForm {
  return {
    enabled: Boolean(membership.organization_name),
    name: membership.organization_name ?? "",
    number:
      membership.organization_number === undefined
        ? undefined
        : (membership.organization_number ?? ""),
  };
}

const numberIsValid = (value?: string) =>
  !value?.trim() || /^[0-9]{6}-[0-9]{4}$/.test(value.trim());

export function organizationIsValid(form: OrganizationForm) {
  return (
    !form.enabled ||
    (form.name.trim().length > 0 &&
      form.name.length <= 200 &&
      numberIsValid(form.number))
  );
}

export function organizationValues(form: OrganizationForm): Organization {
  return {
    organization_name: form.enabled ? form.name.trim() : null,
    ...(form.number !== undefined && {
      organization_number: form.enabled ? form.number.trim() || null : null,
    }),
  };
}

export function OrganizationFields({
  form,
  onChange,
}: {
  form: OrganizationForm;
  onChange: (form: OrganizationForm) => void;
}) {
  const id = useId();
  return (
    <>
      <FormControlLabel
        control={
          <Checkbox
            checked={form.enabled}
            onChange={(e) => onChange({ ...form, enabled: e.target.checked })}
          />
        }
        label="Juridisk person (organisation)"
      />
      {form.enabled && (
        <>
          <div>
            <label className="sb-label" htmlFor={`${id}-name`}>
              Organisationsnamn
            </label>
            <input
              className="sb-input"
              id={`${id}-name`}
              required
              maxLength={200}
              value={form.name}
              onChange={(e) => onChange({ ...form, name: e.target.value })}
            />
          </div>
          {form.number !== undefined && (
            <div>
              <label className="sb-label" htmlFor={`${id}-number`}>
                Organisationsnummer
              </label>
              <input
                className="sb-input"
                id={`${id}-number`}
                aria-describedby={`${id}-format`}
                aria-invalid={!numberIsValid(form.number)}
                value={form.number}
                onChange={(e) => onChange({ ...form, number: e.target.value })}
              />
              <p
                id={`${id}-format`}
                className={
                  numberIsValid(form.number)
                    ? ds["ad-field-hint"]
                    : ds["ad-field-error"]
                }
              >
                Valfritt. Format NNNNNN-NNNN.
              </p>
            </div>
          )}
        </>
      )}
    </>
  );
}
