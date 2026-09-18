#!/usr/bin/env python3
"""Create geocoder-ready, USPS-style US address columns from CSV, TXT, or XLSX files.

This formatter does not validate addresses against USPS or certify deliverability.
It preserves all source columns and adds normalized fields suitable for a geocoder.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any


STATE_ABBREVIATIONS = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI",
    "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
    "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY", "PUERTO RICO": "PR", "GUAM": "GU",
    "AMERICAN SAMOA": "AS", "NORTHERN MARIANA ISLANDS": "MP", "VIRGIN ISLANDS": "VI",
}
VALID_STATES = set(STATE_ABBREVIATIONS.values())

STREET_SUFFIXES = {
    "ALLEY": "ALY", "AVENUE": "AVE", "BOULEVARD": "BLVD", "CIRCLE": "CIR",
    "COURT": "CT", "DRIVE": "DR", "EXPRESSWAY": "EXPY", "HIGHWAY": "HWY",
    "LANE": "LN", "PARKWAY": "PKWY", "PLACE": "PL", "PLAZA": "PLZ",
    "ROAD": "RD", "SQUARE": "SQ", "STREET": "ST", "TERRACE": "TER",
    "TRAIL": "TRL", "WAY": "WAY", "APARTMENT": "APT", "BUILDING": "BLDG",
}
DIRECTIONS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
UNIT_LABELS = {
    "APARTMENT": "APT", "APT": "APT", "BUILDING": "BLDG", "BLDG": "BLDG",
    "DEPARTMENT": "DEPT", "DEPT": "DEPT", "FLOOR": "FL", "FL": "FL",
    "LOT": "LOT", "ROOM": "RM", "RM": "RM", "SPACE": "SPC", "SPC": "SPC",
    "SUITE": "STE", "STE": "STE", "UNIT": "UNIT", "#": "#",
}

# Header aliases are deliberately conservative: automatic detection should not silently
# choose a non-address field just because its name happens to include "address".
ALIASES = {
    "single": ("fulladdress", "address", "streetaddress", "mailingaddress", "addressline1"),
    "street": ("address1", "addr1", "street", "street1", "addressline1", "primaryaddress"),
    "street2": ("address2", "addr2", "street2", "addressline2", "secondaryaddress", "unit"),
    "city": ("city", "municipality", "town"),
    "state": ("state", "stateprovince", "province", "region"),
    "zip": ("zip", "zipcode", "postalcode", "postcode"),
}


def clean(value: Any) -> str:
    """Return a compact display value, treating None as an empty field."""
    return re.sub(r"\s+", " ", str(value or "").strip())


def header_key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def first_alias(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    keys = {header_key(h): h for h in headers}
    return next((keys[a] for a in aliases if a in keys), None)


def resolve_columns(headers: list[str], args: argparse.Namespace) -> dict[str, str | None]:
    explicit_single = args.address_cols
    if explicit_single and explicit_single not in headers:
        raise ValueError(f"Address column not found: {explicit_single}")
    mapping = {
        "single": explicit_single or first_alias(headers, ALIASES["single"]),
        "street": args.street_col or first_alias(headers, ALIASES["street"]),
        "street2": args.street2_col or first_alias(headers, ALIASES["street2"]),
        "city": args.city_col or first_alias(headers, ALIASES["city"]),
        "state": args.state_col or first_alias(headers, ALIASES["state"]),
        "zip": args.zip_col or first_alias(headers, ALIASES["zip"]),
    }
    for name, column in mapping.items():
        if name != "single" and column and column not in headers:
            raise ValueError(f"Column for --{name}-col not found: {column}")
    # Explicit component columns are more trustworthy than a generic full address column.
    if args.street_col:
        mapping["single"] = None
    # "Address line 1" is commonly a component, not a full postal address. When it
    # coincides with the detected street field, keep the separately supplied locality.
    elif mapping["single"] and mapping["single"] == mapping["street"] and any(
        mapping[name] for name in ("street2", "city", "state", "zip")
    ):
        mapping["single"] = None
    return mapping


def replace_words(value: str, replacements: dict[str, str]) -> str:
    for original in sorted(replacements, key=len, reverse=True):
        value = re.sub(rf"\b{re.escape(original)}\b", replacements[original], value)
    return value


def normalize_state(value: str) -> str:
    value = clean(value).upper().replace(".", "")
    return STATE_ABBREVIATIONS.get(value, value)


def normalize_zip(value: str) -> str:
    digits = re.sub(r"[^0-9]", "", clean(value))
    if len(digits) == 9:
        return f"{digits[:5]}-{digits[5:]}"
    return digits


def normalize_unit(value: str) -> str:
    value = clean(value).upper().replace(".", "")
    value = re.sub(r"^#\s*", "# ", value)
    for original in sorted(UNIT_LABELS, key=len, reverse=True):
        value = re.sub(rf"\b{re.escape(original)}\b", UNIT_LABELS[original], value)
    return clean(value)


def split_embedded_unit(address1: str) -> tuple[str, str]:
    """Move an end-of-line apartment/suite marker to its own field when present."""
    labels = "|".join(re.escape(label) for label in UNIT_LABELS if label != "#")
    match = re.search(rf"(?:,|\s)\s*((?:{labels})\.?\s+[#A-Z0-9-]+|#\s*[A-Z0-9-]+)\s*$", address1, re.I)
    if not match:
        return address1, ""
    return address1[:match.start()].rstrip(" ,"), normalize_unit(match.group(1))


def normalize_street(value: str) -> str:
    value = clean(value).upper().replace(".", "")
    value = re.sub(r"\s*,\s*", " ", value)
    if re.match(r"^P\s*O\s+BOX\b", value):
        return re.sub(r"^P\s*O\s+BOX\b", "PO BOX", value)
    value = replace_words(value, DIRECTIONS)
    return clean(replace_words(value, STREET_SUFFIXES))


def parse_full_address(value: str) -> dict[str, str]:
    """Parse conventional comma-delimited US address text conservatively."""
    parts = [clean(part) for part in value.split(",") if clean(part)]
    result = {"address1": "", "address2": "", "city": "", "state": "", "zip": ""}
    if not parts:
        return result
    # The final chunk commonly contains both state and ZIP; remove them from right to left.
    last = parts[-1]
    terminal_consumed = False
    zip_match = re.search(r"(?:^|\s)(\d{5}(?:[- ]?\d{4})?)\s*$", last)
    if zip_match:
        result["zip"] = zip_match.group(1)
        last = last[:zip_match.start()].strip(" ,")
        terminal_consumed = True
    state_match = re.search(r"(?:^|\s)([A-Za-z]{2}|[A-Za-z ]+)\s*$", last)
    if state_match:
        possible_state = normalize_state(state_match.group(1))
        if possible_state in VALID_STATES:
            result["state"] = possible_state
            last = last[:state_match.start()].strip(" ,")
            terminal_consumed = True
    if last:
        # A final residual after state/ZIP is usually city text (e.g. "Austin TX").
        result["city"] = last
        terminal_consumed = True
    if terminal_consumed:
        parts.pop()
    # A sheet may put state and ZIP in separate comma-delimited fields.
    if not result["state"] and parts:
        possible_state = normalize_state(parts[-1])
        if possible_state in VALID_STATES:
            result["state"] = possible_state
            parts.pop()
    if not result["city"] and len(parts) >= 2:
        result["city"] = parts.pop()
    if parts:
        result["address1"] = parts.pop(0)
    if parts:
        result["address2"] = ", ".join(parts)
    # No comma case: retain the entire value as address1 instead of guessing city boundaries.
    if not result["address1"]:
        result["address1"] = value
    return result


def normalize_row(row: dict[str, Any], columns: dict[str, str | None]) -> dict[str, str]:
    if columns["single"]:
        raw = clean(row.get(columns["single"] or "", ""))
        values = parse_full_address(raw)
    else:
        values = {"address1": clean(row.get(columns["street"] or "", "")),
                  "address2": clean(row.get(columns["street2"] or "", "")),
                  "city": clean(row.get(columns["city"] or "", "")),
                  "state": clean(row.get(columns["state"] or "", "")),
                  "zip": clean(row.get(columns["zip"] or "", ""))}
    address1, embedded_unit = split_embedded_unit(values["address1"])
    address2 = values["address2"] or embedded_unit
    address1 = normalize_street(address1)
    address2 = normalize_unit(address2)
    city = clean(values["city"]).upper()
    state = normalize_state(values["state"])
    postal_code = normalize_zip(values["zip"])
    full = ", ".join(part for part in (address1, address2, city, " ".join(x for x in (state, postal_code) if x)) if part)
    missing = [name for name, value in (("address", address1), ("city", city), ("state", state), ("zip", postal_code)) if not value]
    status = "OK" if not missing and state in VALID_STATES and re.fullmatch(r"\d{5}(?:-\d{4})?", postal_code) else "REVIEW: " + ", ".join(missing or ["invalid state or ZIP"])
    return {"normalized_address1": address1, "normalized_address2": address2,
            "normalized_city": city, "normalized_state": state, "normalized_zip": postal_code,
            "normalized_full_address": full, "normalization_status": status}


def read_rows(path: Path, sheet: str | None) -> tuple[list[str], list[dict[str, Any]]]:
    if path.suffix.lower() in {".csv", ".txt"}:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            if path.suffix.lower() == ".txt":
                sample = handle.read(8192)
                handle.seek(0)
                first_line = next((line for line in sample.splitlines() if clean(line)), "")
                # Sniffer can mistake a comma-containing street address for a header.
                # Street numbers and PO Boxes are strong evidence of an address list.
                looks_like_address_list = bool(re.match(r"\s*(?:\d|P\s*\.?\s*O\s*\.?\s+BOX\b)", first_line, re.I))
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
                    has_header = csv.Sniffer().has_header(sample)
                except csv.Error:
                    dialect, has_header = csv.excel, False
                if looks_like_address_list or not has_header:
                    # A simple text file is treated as one address per non-blank line.
                    rows = [{"address": clean(line)} for line in handle if clean(line)]
                    return ["address"], rows
                reader = csv.DictReader(handle, dialect=dialect)
            else:
                reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("Delimited text file has no header row")
            return list(reader.fieldnames), list(reader)
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("Input must be a .csv, .txt, .xlsx, or .xlsm file")
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("XLSX support requires openpyxl: python3 -m pip install -r requirements.txt") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet] if sheet else workbook.active
    rows = worksheet.iter_rows(values_only=True)
    headers = [clean(value) for value in next(rows, ())]
    if not headers or not any(headers):
        raise ValueError("Worksheet has no header row")
    return headers, [dict(zip(headers, values)) for values in rows]


def write_rows(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    if path.suffix.lower() in {".csv", ".txt"}:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Output must end in .csv, .txt, or .xlsx")
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("XLSX support requires openpyxl: python3 -m pip install -r requirements.txt") from exc
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet("normalized_addresses")
    worksheet.append(headers)
    for row in rows:
        worksheet.append([row.get(header, "") for header in headers])
    workbook.save(path)


def default_output_path(input_path: Path) -> Path:
    """Place the cleaned file beside its source, using an output-compatible suffix."""
    suffix = ".xlsx" if input_path.suffix.lower() == ".xlsm" else input_path.suffix
    return input_path.with_name(f"{input_path.stem}_clean{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Add USPS-style address columns to a CSV, TXT, or XLSX file.")
    parser.add_argument("input", type=Path, help="Input .csv, .txt, .xlsx, or .xlsm file")
    parser.add_argument("output", type=Path, nargs="?", help="Output .csv, .txt, or .xlsx file (default: INPUT_clean beside input)")
    parser.add_argument("--sheet", help="Worksheet name for XLSX input (default: active sheet)")
    parser.add_argument("--address-cols", help="Single full-address column")
    parser.add_argument("--street-col", help="Street/address line 1 column")
    parser.add_argument("--street2-col", help="Street/address line 2 or unit column")
    parser.add_argument("--city-col", help="City column")
    parser.add_argument("--state-col", help="State column")
    parser.add_argument("--zip-col", help="ZIP/postal-code column")
    args = parser.parse_args()
    try:
        args.output = args.output or default_output_path(args.input)
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Output path must differ from input path")
        headers, rows = read_rows(args.input, args.sheet)
        columns = resolve_columns(headers, args)
        if not columns["single"] and not columns["street"]:
            raise ValueError("Could not find an address column. Supply --address-cols or --street-col.")
        additions = list(normalize_row({}, columns).keys())
        collisions = set(headers).intersection(additions)
        if collisions:
            raise ValueError(f"Output column name(s) already exist: {', '.join(sorted(collisions))}")
        output_rows = []
        for row in rows:
            output_rows.append({**row, **normalize_row(row, columns)})
        write_rows(args.output, headers + additions, output_rows)
        print(f"Wrote {len(output_rows)} rows to {args.output}")
        print("Detected columns: " + ", ".join(f"{key}={value}" for key, value in columns.items() if value))
        return 0
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
