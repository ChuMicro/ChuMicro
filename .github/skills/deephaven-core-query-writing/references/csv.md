# Deephaven CSV Reference

Use `deephaven.read_csv` (not pandas) to keep data in-engine.

**Default: `read_csv(path)` with no `header=`, then verify with `.meta_table`.** Auto-inference picks `string`/`int*`/`double`/`bool`; blanks become `NaN`/null and unparseable values (`-`, `N/A`) fall back to `string` rather than failing. `header=` is **all-or-nothing** — every column listed, file header replaced — so reach for it only for headerless files or wholesale retyping. **Bias toward post-import fixes in `.update()`:** cast single problem columns there, and for chart x-axes parse to `Instant` with `parseInstant()` (`"Ts = parseInstant(DateStr + \`T00:00:00 UTC\`)"`for`YYYY-MM-DD`), never `parseLocalDate`(see`references/time-operations.md`). Don't blanket-coerce numerics to `string` "to be safe" — it forces wrong choices downstream.

To clean: `rename_columns` or `view` aliases to rename; `.where()` to filter; `isNull()` + ternaries for nulls; cast strings via `Double.parseDouble()` / `Integer.parseInt()` in `.update()`, guarding nullable cols (`isNull(Col) ? null : Integer.parseInt(Col)`).

> If the CSV contains timestamp or date columns, also read `references/time-operations.md` for parsing and timezones.

## read_csv

`read_csv(path, header=None, headless=False, header_row=0, skip_rows=0, num_rows=MAX_LONG, ignore_empty_lines=False, allow_missing_columns=False, ignore_excess_columns=False, delimiter=",", quote='"', ignore_surrounding_spaces=True, trim=False) -> Table`

- `path`: file path or URL. Compressed (`.gz`, `.zip`, `.bz2`, `.7z`, `.zst`, `.tar` variants) read natively — no decompression.
- `header`: dict `{name: dht.DType}` — names + types for every column; replaces the file's header row.
- `headless`: file has no header; columns auto-named `Column1`, `Column2`, ...
- `header_row` / `skip_rows` / `num_rows`: header row index (rows above skipped) / rows to skip after header / cap data rows.
- `ignore_empty_lines` (skip blanks), `allow_missing_columns` (null-fill), `ignore_excess_columns` (drop extras) — tolerance flags.
- `delimiter`: any single char (`","`, `"\t"`, `"|"`, ...). `quote`: quoting char.
- `ignore_surrounding_spaces` (default True): trim **unquoted** whitespace. `trim` (default False): trim **quoted** whitespace. Don't confuse them.

```python
from pathlib import Path

import deephaven.dtypes as dht
from deephaven import read_csv

# URL or local path; compressed extensions also work
t_url = read_csv(
    "https://media.githubusercontent.com/media/deephaven/examples/main/Iris/csv/iris.csv"
)

# Alternative delimiters — any character works
Path("/tmp/test.tsv").write_text("Name\tValue\nAlpha\t10\nBeta\t20\n")
Path("/tmp/test.psv").write_text("Name|Value\nAlpha|10\nBeta|20\n")
t_tsv = read_csv("/tmp/test.tsv", delimiter="\t")
t_psv = read_csv("/tmp/test.psv", delimiter="|")

# Headerless + explicit header dict for names and types
Path("/tmp/headerless.csv").write_text(
    "2024-06-01,AAPL,153.0,1000000\n2024-06-02,GOOG,142.0,800000\n"
)
header = {
    "Date": dht.string,
    "Symbol": dht.string,
    "Price": dht.double,
    "Volume": dht.int64,
}
t = read_csv("/tmp/headerless.csv", header=header, headless=True)
```

### Data types (`deephaven.dtypes as dht`)

| Constant | Use for |
|---|---|
| `dht.string` | Text |
| `dht.bool_` | True/false |
| `dht.int16` / `dht.int32` / `dht.int64` | Integers (small/std/large) |
| `dht.float32` / `dht.double` | Decimals (float64) |
| `dht.Instant` | Timestamps (ISO-8601) |
| `dht.LocalDate` / `dht.LocalTime` | Date-only / time-only |

### Column name sanitization (warning)

`read_csv` legalizes headers automatically — original CSV names won't work after import. Spaces/dashes -> `_`; other illegal chars (`.`, `/`, `#`, `@`, `%`, `(`, `)`, ...) removed; `$` and `_` kept; leading digit gets `column_` prefix; duplicates get `_2` suffix. Examples: `Annual Income (k$)` -> `Annual_Income_k$`, `State/UnionTerritory` -> `StateUnionTerritory`, `1st Place` -> `column_1st_Place`. Check `t.meta_table` for actual names.

### Messy files

Combine tolerance flags with an explicit `header`:

```python
from pathlib import Path

import deephaven.dtypes as dht
from deephaven import read_csv

Path("/tmp/messy.csv").write_text(
    "Date,Symbol,Open,High,Low,Close,Volume,Status,TimestampStr\n"
    "\n"
    " 2024-06-01 , AAPL ,150,155,149,153,1000000,ok,2024-06-01T16:00:00Z,extra\n"
    "2024-06-02,GOOG,140,143,139,142,800000,ok,2024-06-02T16:00:00Z\n"
    "2024-06-03,MSFT,300,305,299,302,500000,ok,2024-06-03T16:00:00Z\n"
)
header = {
    "Date": dht.string,
    "Symbol": dht.string,
    "Open": dht.double,
    "High": dht.double,
    "Low": dht.double,
    "Close": dht.double,
    "Volume": dht.int64,
    "Status": dht.string,
    "TimestampStr": dht.string,
}
t = read_csv(
    "/tmp/messy.csv",
    header=header,
    num_rows=3,
    ignore_empty_lines=True,
    allow_missing_columns=True,
    ignore_excess_columns=True,
    trim=True,
)
```

### Non-numeric sentinels (`-`, `N/A`)

Auto-inference already handles these: blanks become `NaN`/null; non-blank tokens (`-`, `N/A`, `unknown`) make the whole column fall back to `string`. No `header=` needed — just clean and cast post-import.

```python
from pathlib import Path

import deephaven.dtypes as dht
from deephaven import read_csv

Path("/tmp/sentinel.csv").write_text("Name,Value\nA,10\nB,-\nC,30\n")

t = read_csv("/tmp/sentinel.csv", header={"Name": dht.string, "Value": dht.string})
t = t.update(
    [
        "Value = Value.equals(`-`) || Value.trim().isEmpty()"
        " ? NULL_DOUBLE : Double.parseDouble(Value)"
    ]
)
```

### Trailing-comma / phantom column (warning)

A header row ending with `,` creates an unnamed column and throws `ArrayIndexOutOfBoundsException`. Neither `allow_missing_columns` nor `ignore_excess_columns` fixes it — preprocess to strip trailing commas.

## write_csv

`write_csv(table, path, cols=None)` — `cols` defaults to all columns. Nulls are written as empty fields.

```python
from deephaven import empty_table, write_csv

t = empty_table(100).update(["X = 0.1 * i", "Y = sin(X)", "Z = cos(X)"])
write_csv(t, "/tmp/output.csv")
write_csv(t, "/tmp/partial.csv", cols=["X", "Y"])
```
