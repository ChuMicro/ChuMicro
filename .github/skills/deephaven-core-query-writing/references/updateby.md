# Deephaven update_by Reference

Rolling, cumulative, window ops adding columns from row-by-row calc.

## Operations

Numeric cols only. Every `_tick` op has a `_time` twin: first arg `ts_col`, uses ISO 8601 `rev_time`/`fwd_time` (`PT1s`, `PT5m`, `PT1h30m`) instead of `rev_ticks`/`fwd_ticks`. `rev_ticks` = rows back incl. current; `fwd_ticks` = rows forward (default 0). `_tick` for row counts, `_time` for irregular data.

- `cum_{sum,prod,min,max}`; `cum_count_where(col=, filters=)`
- `forward_fill` (NULL/NaN -> last valid); `delta(delta_control=)`
- `rolling_{sum,avg,min,max,prod,count,std}_tick/_time`
- `rolling_wavg_tick/_time(wcol=)`; `rolling_group_tick/_time` (window as array)
- `rolling_count_where_tick/_time(col=, filters=)`; `rolling_formula_tick/_time`
- `ema_tick/_time`, `ems_tick/_time`, `emmin/emmax/emstd_tick/_time` (`decay_ticks=`/`decay_time=`)

## Example (cumulative + rolling + EMA, tick + time)

```python
# ruff: noqa: I001
from deephaven import empty_table
from deephaven.updateby import (
    cum_count_where,
    cum_max,
    cum_min,
    cum_prod,
    cum_sum,
    delta,
    ema_tick,
    ema_time,
    emmax_tick,
    emmin_tick,
    ems_tick,
    emstd_tick,
    forward_fill,
    rolling_avg_tick,
    rolling_avg_time,
    rolling_count_tick,
    rolling_count_where_tick,
    rolling_count_where_time,
    rolling_group_tick,
    rolling_max_tick,
    rolling_min_tick,
    rolling_prod_tick,
    rolling_std_tick,
    rolling_sum_tick,
    rolling_wavg_tick,
    rolling_wavg_time,
)

t = empty_table(40).update(
    [
        "Sym = i < 20 ? `AAPL` : `GOOG`",
        "Timestamp = parseInstant(`2024-01-01T09:30:00 America/New_York`) + i * 'PT1m'",
        "Price = (Sym == `AAPL` ? 150.0 : 140.0) + (i == 5 ? Double.NaN : i * 0.4)",
        "PrevPrice = (Sym == `AAPL` ? 149.0 : 139.0) + i * 0.4",
        "Qty = (int)(100 + i * 10)",
        "Volume = (int)(1000 + i * 50)",
    ]
)

t.update_by(
    [
        # Cumulative / fill / delta
        cum_sum(cols=["Tot = Qty"]),
        cum_prod(cols=["Prod = Qty"]),
        cum_min(cols=["Mn = Qty"]),
        cum_max(cols=["Mx = Qty"]),
        cum_count_where(col="CntBig", filters="Qty > 200"),
        forward_fill(cols=["Filled = Price"]),  # NaN -> last valid
        delta(cols=["Change = Price"]),  # diff from prev row
        # Rolling tick
        rolling_avg_tick(cols=["MA10 = Price"], rev_ticks=10),
        rolling_sum_tick(cols=["Sum10 = Qty"], rev_ticks=10),
        rolling_min_tick(cols=["Min10 = Price"], rev_ticks=10),
        rolling_max_tick(cols=["Max10 = Price"], rev_ticks=10),
        rolling_std_tick(cols=["SD = Price"], rev_ticks=20),
        rolling_prod_tick(cols=["P5 = Price"], rev_ticks=5),
        rolling_count_tick(cols=["NN = Price"], rev_ticks=10),
        rolling_avg_tick(cols=["MA_C = Price"], rev_ticks=5, fwd_ticks=5),  # centered
        rolling_wavg_tick(wcol="Volume", cols=["VWAP = Price"], rev_ticks=20),
        rolling_group_tick(cols=["Last5 = Price"], rev_ticks=5),
        rolling_count_where_tick(col="Up", filters="Price > PrevPrice", rev_ticks=10),
        # EMA family
        ema_tick(decay_ticks=10, cols=["EMA = Price"]),
        ems_tick(decay_ticks=10, cols=["EMS = Qty"]),
        emmin_tick(decay_ticks=10, cols=["EMMin = Price"]),
        emmax_tick(decay_ticks=10, cols=["EMMax = Price"]),
        emstd_tick(decay_ticks=10, cols=["EMStd = Price"]),
        # Time-based (ts_col first, ISO durations)
        rolling_avg_time("Timestamp", cols=["MA_5m = Price"], rev_time="PT5m"),
        rolling_avg_time(
            "Timestamp", cols=["MA_TC = Price"], rev_time="PT2m", fwd_time="PT2m"
        ),  # noqa: E501
        rolling_wavg_time(
            "Timestamp", wcol="Volume", cols=["TVWAP = Price"], rev_time="PT10m"
        ),  # noqa: E501
        rolling_count_where_time(
            "Timestamp", col="UpT", filters="Price > PrevPrice", rev_time="PT10m"
        ),  # noqa: E501
        ema_time("Timestamp", decay_time="PT5m", cols=["EMAt = Price"]),
    ],
    by=["Sym"],
)
```

## Rolling Formula (Custom)

`formula_param` is the window-data alias in `formula`; formulas can only reference this alias, not column names. One input col per formula (no multi-col). Funcs: `max`, `min`, `sum`, `count`, `avg`, `var`, `std`, `first`, `last`, `countDistinct`, `x[0]`, `x.size()`.

```python
from deephaven import empty_table
from deephaven.updateby import rolling_formula_tick, rolling_formula_time

t = empty_table(50).update(
    [
        "Sym = i % 2 == 0 ? `AAPL` : `GOOG`",
        "Timestamp = parseInstant(`2024-01-01T09:30:00 America/New_York`) + i * 'PT1m'",
        "Price = 150.0 + Math.sin(i * 0.1) * 10",
    ]
)

t.update_by(
    [
        rolling_formula_tick(
            formula="max(x) - min(x)",
            formula_param="x",
            cols=["Range = Price"],
            rev_ticks=10,
        ),
        rolling_formula_time(
            "Timestamp",
            formula="max(x) - min(x)",
            formula_param="x",
            cols=["TimeRange = Price"],
            rev_time="PT5m",
        ),
    ],
    by=["Sym"],
)
```

## Patterns: MACD, Bollinger, NaN handling

MACD = fast EMA - slow EMA, then signal. Bollinger = MA +/- 2 stddev. EMA `op_control=` modes: `SKIP` (default), `POISON` (NaN propagates), `RESET` (restart at next valid). `delta(delta_control=)` modes: `NULL_DOMINATES` (default), `VALUE_DOMINATES`, `ZERO_DOMINATES`.

```python
from deephaven import empty_table
from deephaven.updateby import (
    BadDataBehavior,
    OperationControl,
    ema_tick,
    rolling_avg_tick,
    rolling_std_tick,
)

t = empty_table(30).update(
    [
        "Sym = `AAPL`",
        "Price = i == 5 ? Double.NaN : 150.0 + i * 0.5",
    ]
)

macd = (
    t.update_by(
        [
            ema_tick(decay_ticks=12, cols=["EMA12 = Price"]),
            ema_tick(decay_ticks=26, cols=["EMA26 = Price"]),
        ],
        by=["Sym"],
    )
    .update(["MACD = EMA12 - EMA26"])
    .update_by([ema_tick(decay_ticks=9, cols=["Signal = MACD"])], by=["Sym"])
    .update(["Hist = MACD - Signal"])
)

bands = t.update_by(
    [
        rolling_avg_tick(cols=["MA = Price"], rev_ticks=20),
        rolling_std_tick(cols=["SD = Price"], rev_ticks=20),
    ],
    by=["Sym"],
).update(["Up = MA + 2 * SD", "Lo = MA - 2 * SD"])

oc = OperationControl(on_nan=BadDataBehavior.RESET)
t.update_by([ema_tick(decay_ticks=3, cols=["E = Price"], op_control=oc)], by=["Sym"])
```
