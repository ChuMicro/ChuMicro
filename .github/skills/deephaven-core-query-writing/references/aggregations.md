# Deephaven Aggregations Reference

## Dedicated Aggregations

Single-operation aggregations optimized for common cases.

```python
from deephaven import empty_table

t = empty_table(6).update(
    [
        "Sym = i < 2 ? `AAPL` : (i < 4 ? `GOOG` : `MSFT`)",
        "Price = 100.0 + i",
        "Qty = 100 + i*10",
        "Weight = 0.1 * (i+1)",
        "Value = Price * Qty",
    ]
)

# (by) family operates on ALL non-key columns:
# sum_by, avg_by, min_by, max_by, median_by, std_by, var_by,
# abs_sum_by, first_by, last_by
t.view(["Price", "Qty", "Value"]).sum_by()  # no arg: entire table (numeric only)
t.sum_by("Sym")  # single key
t.sum_by(["Sym", "Weight"])  # multiple keys
t.avg_by("Sym")
t.median_by("Sym")

# count_by(out_col, by) — first arg is the OUTPUT column name
t.count_by("Count")
t.count_by("Count", "Sym")
t.count_by("Count", ["Sym", "Weight"])

# (n, by) and (wcol, by) — first arg is NOT a key
t.head_by(5, "Sym")
t.tail_by(5, "Sym")
t.weighted_avg_by("Weight", "Sym")  # wcol first, then by
t.weighted_sum_by("Weight", "Sym")
```

**Warning:** dedicated aggs (`avg_by`, `std_by`, `var_by`, `median_by`, etc.) throw `UnsupportedOperationException: Unsupported type class java.lang.String` on String/Timestamp non-key columns, and `aggAllBy has no columns to aggregate` when all non-key columns are dropped. **Fix:** narrow to key + numeric cols via `.view()`/`.select()`, use `select_distinct` for unique keys, or `count_by` for counts.

```python
from deephaven import agg, empty_table

t = empty_table(3).update(
    [
        "Sym = i < 2 ? `AAPL` : `GOOG`",
        "Exchange = i < 2 ? `NYSE` : `NASDAQ`",
        "Price = 150.0 + i",
    ]
)
# WRONG: t.avg_by("Sym")  -> throws on Exchange (String)
t.view(["Sym", "Price"]).avg_by("Sym")  # narrow first
t.agg_by(
    [agg.avg(cols=["AvgPrice = Price"])], by=["Sym"]
)  # explicit cols ignore non-numerics
```

## Combined Aggregations (agg_by)

Multiple aggregations in one pass — more efficient than separate calls. Import `from deephaven import agg`. Trailing underscores on `sum_`, `min_`, `max_`, `count_` avoid Python keyword/builtin clash.

```python
from deephaven import agg, empty_table

t = empty_table(4).update(
    [
        "Sym = i < 2 ? `AAPL` : `GOOG`",
        "Price = 140.0 + i*2",
        "Qty = 100 + i*50",
        "Weight = 0.1 * (i+1)",
        "Timestamp = parseInstant(`2024-06-01T10:00:00 UTC`) + i * 'PT1h'",
    ]
)

result = t.agg_by(
    [
        agg.avg(cols=["A = Price"]),
        agg.sum_(cols=["S = Qty"]),
        agg.min_(cols=["Mn = Price"]),
        agg.max_(cols=["Mx = Price"]),
        agg.median(cols=["Md = Price"]),
        agg.std(cols=["Sd = Price"]),
        agg.var(cols=["V = Price"]),
        agg.abs_sum(cols=["AS = Qty"]),
        agg.weighted_avg(wcol="Weight", cols=["WA = Price"]),
        agg.weighted_sum(wcol="Weight", cols=["WS = Price"]),
        agg.count_(col="N"),
        agg.count_distinct(cols=["ND = Price"]),
        agg.count_where(col="Hi", filters="Price > 141"),
        agg.first(cols=["F = Timestamp"]),
        agg.last(cols=["L = Timestamp"]),
        agg.group(cols=["G = Price"]),  # collect into array
        agg.distinct(cols=["D = Price"]),  # distinct values as array
        agg.pct(percentile=0.5, cols=["P50 = Price"]),
        agg.pct(percentile=0.95, cols=["P95 = Price"]),
    ],
    by=["Sym"],
)
```

More aggregators (`sorted_first`/`sorted_last` pick by another col's order; `formula` is a custom expr where `formula_param` names the var, `cols` maps `Result=Source`; `partition` returns a sub-table per group) and kwargs (`preserve_empty=True` keeps rows for groups emptied after updates; `initial_groups` pre-defines group keys):

```python
from deephaven import agg, empty_table, new_table
from deephaven.column import string_col

t = empty_table(4).update(
    [
        "Sym = i < 2 ? `AAPL` : `GOOG`",
        "SortCol = new int[]{2,1,4,3}[i]",
        "Val = 100.0 * (i+1)",
    ]
)
all_syms = new_table([string_col("Sym", ["AAPL", "GOOG", "MSFT"])])
t.agg_by(
    aggs=[
        agg.sorted_first(order_by="SortCol", cols=["FirstVal = Val"]),
        agg.sorted_last(order_by="SortCol", cols=["LastVal = Val"]),
        agg.formula(
            formula="max(each) - min(each)", formula_param="each", cols=["Range = Val"]
        ),
        agg.partition(col="SubTable", include_by_columns=False),
    ],
    by=["Sym"],
    preserve_empty=True,
    initial_groups=all_syms,
)
```

## Grouping, Ungrouping, Partitioning

```python
from deephaven import agg, empty_table
from deephaven.execution_context import get_exec_ctx

t = empty_table(4).update(
    ["Sym = i < 2 ? `AAPL` : `GOOG`", "Price = 140.0 + i*2", "Qty = 100 + i*50"]
)

# group_by collapses rows into arrays per key; ungroup explodes back
grouped = t.group_by("Sym")
grouped.ungroup(["Price", "Qty"])  # specific cols; ungroup() = all array cols

# partition_by splits into sub-tables per key
p = t.partition_by("Sym")
p.constituent_tables
p.get_constituent(["AAPL"])
p.keys()
p.merge()

# transform applies fn to each constituent (needs exec context)
ctx = get_exec_ctx()


def add_rank(sub):
    with ctx:
        return sub.update(["Rank = ii + 1"])


p.transform(add_rank).merge()

# partitioned_agg_by aggregates, returns PartitionedTable
t.partitioned_agg_by(aggs=[agg.avg(cols=["A = Price"])], by=["Sym"])
```

## Common Patterns

```python
from deephaven import agg, empty_table

# OHLCV candlestick
trades = empty_table(6).update(
    [
        "Sym = i < 3 ? `AAPL` : `GOOG`",
        "TimeBucket = `10:00`",
        "Price = 140.0 + i*2",
        "Qty = 100 + i*50",
    ]
)
ohlcv = trades.agg_by(
    [
        agg.first(cols=["Open = Price"]),
        agg.max_(cols=["High = Price"]),
        agg.min_(cols=["Low = Price"]),
        agg.last(cols=["Close = Price"]),
        agg.sum_(cols=["Volume = Qty"]),
    ],
    by=["Sym", "TimeBucket"],
)

# Top N per group
scores = empty_table(8).update(
    ["Category = i < 4 ? `A` : `B`", "Value = (double)((i * 37) % 80 + 10)"]
)
top3 = scores.sort_descending("Value").head_by(3, "Category")

# Count with %
items = empty_table(6).update(["Category = i < 3 ? `A` : (i < 5 ? `B` : `C`)"])
counts = items.agg_by([agg.count_(col="Count")], by=["Category"])
total = counts.view(["Total = Count"]).sum_by()
result = counts.natural_join(total, on=[]).update(["Pct = Count / Total * 100"])
```

## Memory Warning

Aggregation keys persist in worker memory for its lifetime even after rows are removed; be cautious with high-cardinality keys on long-running workers.

## Documentation URLs

https://deephaven.io/core/docs/reference/table-operations/group-and-aggregate/aggBy.md
https://deephaven.io/core/docs/how-to-guides/combined-aggregations.md
https://deephaven.io/core/docs/reference/table-operations/group-and-aggregate/groupBy.md
https://deephaven.io/core/docs/reference/table-operations/group-and-aggregate/partitionBy.md
