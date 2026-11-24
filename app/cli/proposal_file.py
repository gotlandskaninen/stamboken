"""Private CSV files for proposals reviewed one row at a time."""

import csv
import os

from utils.csv_safe import csv_cell


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
                # csv_cell adds a space to formula-like values. Escape literal leading
                # spaces too, so the snapshot read back for comparison is lossless.
                cells = {
                    k: " " + v if isinstance(v, str) and v.startswith(" ") else csv_cell(v) for k, v in row.items()
                }
                writer.writerow({**cells, "beslut": ""})
    except BaseException:
        os.unlink(path)
        raise


def read_decisions(path, header):
    """Validate the whole file before returning any reviewed rows to a writer."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        if reader.fieldnames != list(header) or "beslut" not in header:
            raise ValueError("Fel rubrikrad i förslagsfilen")
        for row in reader:
            if None in row or None in row.values():
                raise ValueError("Fel antal kolumner i förslagsfilen")
            decision = row["beslut"] or "hoppa över"
            if decision not in ("godkänn", "ändra", "hoppa över"):
                raise ValueError("Okänt beslut i förslagsfilen")
            rows.append({**{k: v.removeprefix(" ") for k, v in row.items()}, "beslut": decision})
    return rows
