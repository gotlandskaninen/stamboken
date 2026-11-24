"""Private CSV files for proposals reviewed one row at a time."""

import csv
import os
import stat

from utils.csv_safe import csv_cell


def proposal_cell(value):
    # csv_cell prefixes formula-like text with a space. Escape literal leading spaces too.
    return " " + value if isinstance(value, str) and value.startswith(" ") else csv_cell(value)


def write_proposals(path, header, rows):
    """Create a spreadsheet-safe UTF-8 CSV with an empty decision on every row."""
    if "beslut" not in header:
        raise ValueError("Rubrikraden saknar beslut")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as dest:
            writer = csv.DictWriter(dest, fieldnames=header, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for row in rows:
                cells = {k: proposal_cell(v) for k, v in row.items()}
                writer.writerow({**cells, "beslut": ""})
    except BaseException:
        os.unlink(path)
        raise


def read_decisions(path, header, *, raw_cells=False):
    """Validate the whole file. Keep spreadsheet escapes when comparing raw cells."""
    rows = []

    def opener(name, flags):
        # A FIFO must reach the regular-file check without waiting for a writer.
        return os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK)

    with open(path, encoding="utf-8-sig", newline="", opener=opener) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Förslagsfilen måste vara en privat, vanlig fil som ägs av den körande användaren")
        reader = csv.DictReader(source, strict=True)
        if reader.fieldnames != list(header) or "beslut" not in header:
            raise ValueError("Fel rubrikrad i förslagsfilen")
        for row in reader:
            if None in row or None in row.values():
                raise ValueError("Fel antal kolumner i förslagsfilen")
            decision = row["beslut"] or "hoppa över"
            if decision not in ("godkänn", "ändra", "hoppa över"):
                raise ValueError("Okänt beslut i förslagsfilen")
            if not raw_cells:
                row = {k: v.removeprefix(" ") for k, v in row.items()}
            rows.append({**row, "beslut": decision})
    return rows
