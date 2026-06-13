# Deephaven Joins Reference

## Overview

| Method | Match | Unmatched | Multiple Right Matches |
|---|---|---|---|
| `natural_join` | Exact | NULL | Errors (or `type=` first/last) |
| `exact_join` | Exact | Errors | Errors (must be 1) |
| `join` | Exact | Excluded | All combinations |
| `aj` | As-of `<=` | NULL | Closest (sorted) |
| `raj` | Reverse as-of `>=` | NULL | Closest (sorted) |
| `range_join` | Range | NULL | Aggregated via `agg.group` |

**Gotchas:**
- Key columns must share type both sides; mismatch raises `Mismatched join types` — cast via `.update` first.
- Non-key column collisions raise `Conflicting column names` — rename via `joins=["NewName = Col"]` or `drop_columns`.
- String date keys are exact-match only; `2024-01-01` vs `01/01/2024` silently yields NULLs.
- `aj`/`raj`: right table must be sorted by the as-of column within each exact-match group.
- `range_join`: static tables only; right table must be sorted by the range column.

## natural_join

Adds right columns; unmatched rows get NULL. Errors on duplicate right keys unless `type=` is set. `on` is str or list; `joins` selects/renames right cols (default: all non-key). Multi-key: `on=["K1", "L = R"]`. Pre-dedupe with `right.last_by("Key")` if needed.

```python
from deephaven import new_table
from deephaven.column import double_col, int_col, string_col
from deephaven.table import NaturalJoinType

L = [string_col("Key", ["A", "B"]), double_col("V", [1.0, 2.0])]
R = [
    string_col("Key", ["A", "B"]),
    double_col("C1", [10.0, 20.0]),
    double_col("C2", [1.0, 2.0]),
]
left, right = new_table(L), new_table(R)

left.natural_join(table=right, on="Key", joins="C1, C2")
left.natural_join(right, on="Key", joins=["NewName = C1"])

# Different key names + multi-key: on=["LK = RK", "Date"]
l2 = new_table([string_col("LK", ["A"]), string_col("D", ["x"])])
r2 = new_table([string_col("RK", ["A"]), string_col("D", ["x"]), int_col("V", [1])])
l2.natural_join(r2, on=["LK = RK", "D"])

# Duplicate right keys: pick first/last instead of erroring
dup = new_table([string_col("Key", ["A", "A"]), double_col("I", [10.0, 11.0])])
left.natural_join(dup, on="Key", type=NaturalJoinType.FIRST_MATCH)
left.natural_join(dup, on="Key", type=NaturalJoinType.LAST_MATCH)
```

## exact_join

Like `natural_join` but requires exactly one right match per left row — zero or multiple raises.

```python
from deephaven import new_table
from deephaven.column import double_col, string_col

left = new_table([string_col("Key", ["A", "B"]), double_col("LVal", [1.0, 2.0])])
right = new_table([string_col("Key", ["A", "B"]), double_col("Col1", [10.0, 20.0])])
left.exact_join(right, on="Key", joins="Col1")
```

## join (cross / inner)

Returns every matching combination. `on=[]` gives a Cartesian product. Can explode result size.

```python
from deephaven import new_table
from deephaven.column import double_col, string_col

left = new_table([string_col("Key", ["A", "B"]), double_col("L", [1.0, 2.0])])
right = new_table([string_col("Key", ["A", "B"]), double_col("R", [10.0, 20.0])])

left.join(right, on="Key")  # matching pairs
left.join(right, on=[], joins=["R"])  # full cross product
```

## aj / raj (as-of joins)

`aj` picks the latest right row with `right_ts <= left_ts`; `raj` picks the earliest with `right_ts >= left_ts`. Unmatched left rows get NULL. Last entry in `on` is the as-of match; earlier entries are exact keys.

```python
import datetime

from deephaven import new_table
from deephaven.column import datetime_col, double_col, string_col

UTC = datetime.timezone.utc


def ts(s):
    return datetime.datetime(2024, 6, 1, 10, 0, s, tzinfo=UTC)


T = [string_col("Sym", ["AAPL"] * 2), datetime_col("TS", [ts(1), ts(3)])]
Q = [
    string_col("Sym", ["AAPL"] * 2),
    datetime_col("QT", [ts(0), ts(2)]),
    double_col("Bid", [1.0, 2.0]),
]
trades = new_table(T)
quotes = new_table(Q).sort(["Sym", "QT"])

trades.aj(quotes, on=["Sym", "TS >= QT"], joins=["Bid"])  # <= default
trades.aj(quotes, on=["Sym", "TS > QT"], joins=["Bid"])  # strict <
trades.raj(quotes, on=["Sym", "TS <= QT"], joins=["Bid"])  # >=
```

## range_join

Joins right rows whose key falls in a left-row range, then aggregates. Currently only `agg.group` is supported.

```python
from deephaven import agg, new_table
from deephaven.column import double_col, int_col

left = new_table([int_col("s", [0, 10]), int_col("e", [10, 20])])
right = new_table([int_col("r", [5, 15]), double_col("V", [1.0, 2.0])])

# Inclusive: "<=...<="; exclusive: "<...<"
left.range_join(right, on=["s <= r <= e"], aggs=[agg.group(cols=["M = V"])])
```

## Performance Tips

Filter before joining. Prefer `natural_join` for 1:1 / many-to-one lookups. Use `aj`/`raj` over range comparisons for time-series alignment. Avoid `join` when the right side has many matches per key.
