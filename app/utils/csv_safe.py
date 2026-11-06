"""Spreadsheet formula-injection protection shared by the CSV exports."""

FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Neutralize formula-injection by prefixing risky cells with a space.

    Protects Excel/Numbers users from a text cell (a name, free text) that
    begins with one of the injection prefixes being evaluated as a formula.
    Use on text cells only: a negative number would get mangled.
    """
    if not value:
        return ""
    s = str(value)
    if s[0] in FORMULA_INJECTION_PREFIXES:
        return " " + s
    return s


def csv_cell(value) -> str:
    """A real number as-is (a negative count stays a number); anything else through csv_safe.

    Form data reaches the exports as JSON, so a "count" can be a user-supplied string.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return csv_safe(value)
