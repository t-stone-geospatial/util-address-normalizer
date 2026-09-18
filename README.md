# US address normalizer

A small utility that adds consistent, geocoder-ready US address fields to a CSV, TXT, or XLSX file. It retains every original column and adds normalized street, unit, city, state, ZIP, full-address, and review-status columns.

The formatting is USPS-style (for example, `STREET` becomes `ST` and `Illinois` becomes `IL`), but it does not verify deliverability or provide USPS CASS certification.

## Use it

From this repository, set up the uv environment once:

```bash
uv sync
```

Then point the utility at any source file, from any location:

```bash
uv run python normalize_addresses.py /path/to/contacts.xlsx
```

By default, the cleaned file is written next to the source:

```text
/path/to/contacts.xlsx  →  /path/to/contacts_clean.xlsx
/path/to/contacts.csv   →  /path/to/contacts_clean.csv
/path/to/contacts.txt   →  /path/to/contacts_clean.txt
```

To choose a different destination, supply it as the second argument:

```bash
uv run python normalize_addresses.py /path/to/contacts.csv /other/place/cleaned.csv
```

Common headers such as `address`, `address1`, `city`, `state`, and `zip` are detected automatically. For unusual headers, specify them:

```bash
uv run python normalize_addresses.py contacts.csv \
  --street-col "Mailing street" --street2-col "Unit" \
  --city-col "Locality" --state-col "State name" --zip-col "Postal"
```

Use `--help` to see all options. Rows with incomplete or invalid core components are marked in `normalization_status` for review before geocoding.

`.txt` files may be a comma-, tab-, pipe-, or semicolon-delimited table with a header row, or a simple one-address-per-line list. Cleaned TXT output is comma-delimited so it can include the original address and all added fields.
