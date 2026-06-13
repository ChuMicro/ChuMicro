---
name: deephaven-core-query-writing
description: Work with Deephaven for real-time data processing. Use for table queries, joins, aggregations, time-series, UI dashboards, plotting (dx), Kafka streaming, Iceberg integration. Triggers on mentions of Deephaven, tables or queries, and related concepts.
license: Apache-2.0
metadata:
  author: Deephaven Data Labs
  version: "0.1.0"
---

## References

Read the relevant reference before writing code — Deephaven APIs differ from similar libraries.

| Reference | Read before code that... |
| --- | --- |
| `joins.md` | uses `natural_join`, `aj`, `raj`, `exact_join`, `range_join` |
| `aggregations.md` | uses `agg_by`, `sum_by`, `avg_by`, `count_by`, 20+ aggregators |
| `updateby.md` | uses rolling/cumulative ops, EMAs, forward fill |
| `time-operations.md` | parses/bins/manipulates timestamps; calendars, timezones |
| `kafka.md` | consumes from / produces to Kafka |
| `iceberg.md` | reads/writes Iceberg tables |
| `ui.md` | builds dashboards, components, hooks, `ui.table` |
| `plotting.md` | makes charts with `dx` |
| `csv.md` | imports/exports CSVs, always read when importing CSV |

## Core Principles

- **Never `print()` tables and never convert to pandas just to print.**
- **Filter early.** Put partition/grouping filters first in `where()`.
- **In-engine over UDF.** Each Python call crosses the Java boundary; prefer built-ins, `java.lang.Math`, and the auto-imported query-language functions.
- **Don't use pandas for intermediate steps** — slow and unnecessary. Never use pandas unless specifically asked for.
- **All imports at the top.** No `__import__()` or inline imports.

### Example Table Creation

```python
from deephaven import (
    empty_table,
    new_table,
    ring_table,
    time_table,
)
from deephaven.column import double_col, string_col

# Empty table with formulas
t = empty_table(100).update(["X = i", "Y = X * 2"])

# New table from columns
t = new_table(
    [string_col("Sym", ["AAPL", "GOOG"]), double_col("Price", [150.0, 140.0])]
)

# Ticking time table (real-time); accepts duration strings
t = time_table("PT1s")

# Ring table — bounded size, keeps last N rows
source = time_table("PT1s")
t = ring_table(source, capacity=1000)
```

### Extracting Scalar Values

`print(table)` only shows the object reference. To get actual cell values from a 1-row table, drop to the Java backing: `table.j_table.getColumnSource("Col").get(table.j_table.getRowSet().firstRowKey())`.

### Column Operations

```python
from deephaven import empty_table

t = empty_table(100).update(["A = i", "B = i * 2", "OldName = i", "Unwanted = i"])

# only named cols, results in RAM.
# Best for: subset with expensive formula or frequent access.
t.select(["A", "B", "C = A + B"])

# only named cols, recomputed on access (no RAM).
# Best for: subset with cheap formula, sparse access, or memory pressure.
t.view(["A", "B", "C = A + B"])

# all cols + new, results in RAM.
# Best for: results that feed downstream ops (joins, aggs, further updates).
t.update(["C = A + B", "D = sqrt(C)"])

# all cols + new, recomputed on access.
# Best for: display-only columns, or when memory is a concern.
t.update_view(["C = A + B"])

# all cols + new, memoized by input value.
# Best for: few distinct inputs relative to row count (e.g. category lookups).
t.lazy_update(["C = A + B"])

t.drop_columns(["Unwanted"])
t.select_distinct(["A"])  # unique; multi-col → unique tuples
t.rename_columns(["NewName = OldName"])
```

### Filtering

```python
from deephaven import empty_table, new_table
from deephaven.column import string_col

t = empty_table(4).update(
    [
        "Sym = i % 2 == 0 ? `AAPL` : `GOOG`",
        "Price = 50.0 + i * 50.0",
        "Timestamp = parseInstant(`2024-06-01T00:00:00 UTC`) + i * 'P1d'",
    ]
)
filter_table = new_table([string_col("Sym", ["AAPL"])])

t.where("Price > 100")
t.where(["Sym = `AAPL`", "Price > 100"])  # list = AND
t.where("Sym.startsWith(`A`)")  # Java String methods
t.where("Sym in `AAPL`, `GOOG`")  # set membership (fast)
t.where_in(filter_table, "Sym")  # / where_not_in
t.where("Timestamp > parseInstant(`2024-01-01T00:00:00 America/New_York`)")

sym = "AAPL"  # dynamic — backtick the value
t.where(f"Sym = `{sym}`")
```

### Joins Overview

**Read `references/joins.md` before using joins.**

- **Exact match:** `natural_join` (add cols from right; NULL if no match), `exact_join` (errors unless exactly one match), `join` (all matching combinations).
- **Time-series:** `aj` (closest ≤ timestamp), `raj` (closest ≥ timestamp).
- **Range:** `range_join` — match within a range, aggregate results.
- **Vertical stack:** `from deephaven import merge`; `merge([t1, t2])` (column names and types must match).

### Aggregations Overview

**Read `references/aggregations.md` before using aggregations.**

- **Single stat, all numeric cols:** `sum_by`, `avg_by`, `min_by`, `max_by`, `median_by`, `std_by`, `var_by`, `abs_sum_by` — e.g. `t.sum_by("Sym")`.
- **`count_by("Count", "Sym")`** — row count per group (first arg is output col name).
- **`first_by` / `last_by`**, **`head_by(N, ...)` / `tail_by(N, ...)`** — first/last row(s) per group.
- **`weighted_avg_by` / `weighted_sum_by`** — first arg is the weight col.
- **`agg_by([...], by=[...])`** — multiple aggs in one pass (`agg.avg(...)`, `agg.sum_(...)`, …).
- **`group_by` / `ungroup`** — collect into arrays / explode back. **`partition_by`** — split into sub-tables.

Dedicated aggs operate on ALL non-key columns and throw `UnsupportedOperationException` on String/Timestamp. **Fix:** `.view()` to keep only key + numeric first, or use `agg_by` with explicit `cols`.

### Query String Syntax

**Literals:** Boolean `true`/`false` (lowercase). Int `42`, Long `42L`, Double `3.14` (no `1_000L` underscores). **Bare integers in `/` produce doubles** — `(year / 10) * 10` → `1987.0`; fix with `year - year % 10` or `(int)(year / 10) * 10`. String: backticks. DateTime: `parseInstant(\`2024-01-01T12:00:00 America/New_York\`)` — short aliases like `NY` do NOT work. Duration `'PT1h30m'`. Period `'P1y2m3d'`.

**Built-ins:** `i` row index (0-based); `ii` or `k` row key (stable).

```python
from deephaven import empty_table

# Ternary + null handling
t = empty_table(10).update(
    [
        "Price = i * 25.0",
        "Category = Price > 100 ? `High` : `Low`",
        "Value = i % 2 == 0 ? NULL_INT : i",
        "Safe = isNull(Value) ? 0 : Value",
    ]
)
```

### Data Import/Export

```python
from deephaven import empty_table, read_csv, write_csv
from deephaven.parquet import read, write

t = empty_table(10).update(["X = i", "Y = X * 2"])
write_csv(t, "/tmp/o.csv")
t_csv = read_csv("/tmp/o.csv")
write(t, "/tmp/o.parquet")
t_pq = read("/tmp/o.parquet")
```
