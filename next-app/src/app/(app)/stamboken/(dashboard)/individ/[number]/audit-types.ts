export interface AuditLogEntry {
  id: number;
  /** "public" for trigger rows; "v1" for history imported from the old Stamboken (read-only). */
  schema_name?: string;
  operation: "INSERT" | "UPDATE" | "DELETE";
  changed_fields: string[] | null;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  changed_by: string | null;
  changed_at: string;
  transaction_id: number | null;
}

export interface AuditLogResponse {
  status: string;
  data: AuditLogEntry[];
  total: number;
  page: number;
  per_page: number;
}
