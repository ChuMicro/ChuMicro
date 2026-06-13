# Deephaven Express (dx) Plotting

**CRITICAL: ALWAYS use `from deephaven.plot import express as dx`. NEVER `import plotly.express` directly.**

`dx` mirrors the Plotly Express API for tables but is **not a full drop-in**. Unsupported kwargs (raise `TypeError`): `trendline`, `marginal_x`, `marginal_y`, `facet_col`, `facet_row`, `animation_frame`. Workarounds:
- **Trendline:** compute the regression as a column with `update`/`update_by`, then overlay a second `dx.line` via `dx.layer`.
- **Faceting:** build one plot per group, arrange with `dx.make_subplots`.

**Sample tables:** `dx.data.stocks()`, `dx.data.iris()`, `dx.data.tips()`, `dx.data.gapminder()`.

## Basic Pattern

```python
from deephaven.plot import express as dx

t = dx.data.stocks()
plot = dx.line(t, x="Timestamp", y="Price", by="Sym")
```

## Available Plot Types

| Function | Use Case | Function | Use Case |
|---|---|---|---|
| `dx.line` | Time series | `dx.scatter` | Correlations, clusters |
| `dx.bar` | Category compare | `dx.histogram` | Distributions (numeric only) |
| `dx.area` | Cumulative totals | `dx.pie` | Proportions |
| `dx.candlestick` | OHLC bodies | `dx.ohlc` | OHLC ticks |
| `dx.box` | Distribution summary | `dx.violin` | Full distribution shape |
| `dx.density_heatmap` | Joint distributions | `dx.density_map` | Geographic density |
| `dx.strip` | Individual points | `dx.indicator` | KPI / gauge |
| `dx.funnel` | Funnel stages | `dx.funnel_area` | Proportional funnel |
| `dx.timeline` | Gantt / time ranges | `dx.treemap` | Nested rectangles |
| `dx.sunburst` | Radial hierarchy | `dx.icicle` | Hierarchical bars |
| `dx.scatter_3d` / `dx.line_3d` | 3D | `dx.scatter_geo` / `dx.line_geo` | Geographic |
| `dx.scatter_map` / `dx.line_map` | Map | `dx.scatter_polar` / `dx.line_polar` | Polar |
| `dx.scatter_ternary` / `dx.line_ternary` | Ternary | | |

Docs per function: `https://deephaven.io/core/plotly/docs/<function_name>.md`.

**Caveats:**
- **`dx.bar` plots values as-is** — pre-aggregate with `agg_by`/`count_by` first.
- **`dx.histogram` only accepts numeric columns** — for categorical counts, pre-aggregate then use `dx.bar`.
- **String x-axis renders in insertion order**, not sorted — sort the table or convert to a temporal type first.
- **Time axes accept only `Instant` or `ZonedDateTime`.** Any other type produces a broken chart. If a column isn't already `Instant` or `ZonedDateTime`, `parseInstant(...)` it before charting.

## Common Parameters

`by=`, `color=`, `symbol=`, `size=`, `line_dash=` partition by column values into separate traces. `by=` is preferred for ticking data (uses server-side `partition_by`). Multiple grouping cols: `by=["Species", "PetalLength"]`.

Bar grouping uses `barmode="group"` (side-by-side), `"stack"`, or `"overlay"`.

```python
from deephaven.plot import express as dx

# Bar grouping
t = dx.data.tips()
dx.bar(t, x="Day", y="TotalBill", by="Sex", barmode="group")

# Visual mapping: color/symbol/size from columns
iris = dx.data.iris()
dx.scatter(
    iris,
    x="SepalLength",
    y="SepalWidth",
    color="Species",
    symbol="Species",
    size="PetalLength",
)
```

## Title, Axes, and Multiple Y Axes

`title=` works on every plot type. Multiple Y axes via `y=[col1, col2]` + `yaxis_sequence=[1, 2]`. Docs: `https://deephaven.io/core/plotly/docs/multiple-axes.md`.

```python
from deephaven.plot import express as dx

t = dx.data.stocks().where("Sym = `DOG`")
dx.line(t, x="Timestamp", y=["Price", "Size"], title="DOG", yaxis_sequence=[1, 2])
```

## Financial Charts, Subplots, Layers

```python
from deephaven import empty_table
from deephaven.plot import express as dx

ohlc = empty_table(20).update(
    [
        "Timestamp = parseInstant(`2024-06-01T10:00:00 UTC`) + i * 'PT1m'",
        "Open = 150.0 + i",
        "High = Open + 3.0",
        "Low = Open - 2.0",
        "Close = Open + (i % 2 == 0 ? 1.0 : -1.0)",
        "MovingAvg = 150.0 + i * 0.5",
    ]
)

candle = dx.candlestick(
    ohlc,
    x="Timestamp",
    open="Open",
    high="High",
    low="Low",
    close="Close",
    increasing_color_sequence=["green"],
    decreasing_color_sequence=["red"],
)

# dx.layer — stack plot types on one chart
layered = dx.layer(candle, dx.line(ohlc, x="Timestamp", y="MovingAvg"))

# dx.make_subplots — arrange multiple plots in a grid
sub = empty_table(100).update(
    ["X = i", "Y = Math.sin(i * 0.1) * 10", "Value = randomDouble(0, 100)"]
)
combined = dx.make_subplots(
    dx.line(sub, x="X", y="Y"),
    dx.scatter(sub, x="X", y="Y"),
    dx.histogram(sub, x="Value"),
    rows=2,
    cols=2,
)
```

## Interactive Filtering with `deephaven.ui`

`dx` handles liveness internally — no explicit scope management needed.

```python
from deephaven import ui
from deephaven.plot import express as dx

stocks = dx.data.stocks()


# Pattern 1: use_memo + where (simple; recomputes on each change)
@ui.component
def filtered_plot(t):
    sym, set_sym = ui.use_state("DOG")
    filtered = ui.use_memo(lambda: t.where(f"Sym = `{sym}`"), [sym])
    plot = ui.use_memo(lambda: dx.line(filtered, x="Timestamp", y="Price"), [filtered])
    return [ui.text_field(value=sym, on_change=set_sym, label="Symbol"), plot]


# Pattern 2: partition_by (faster repeated filtering, more memory)
@ui.component
def partitioned_plot(t):
    sym, set_sym = ui.use_state("DOG")
    partitioned = ui.use_memo(lambda: t.partition_by(["Sym"]), [])
    constituent = ui.use_memo(lambda: partitioned.get_constituent(sym), [sym])
    plot = ui.use_memo(
        lambda: dx.line(constituent, x="Timestamp", y="Price"), [constituent]
    )
    return [ui.text_field(value=sym, on_change=set_sym, label="Symbol"), plot]


result = filtered_plot(stocks)
```

**Pattern 3 — dynamic plot type:** keep the kind in `use_state`, look up the function in a dict (`fn = {"Line": dx.line, "Scatter": dx.scatter}[kind]`), then call `fn(t, x=..., y=...)` inside `ui.use_memo([kind])`.

## `unsafe_update_figure` — advanced customization

Access the underlying Plotly Figure for tweaks the wrapper doesn't expose.

```python
from deephaven import empty_table
from deephaven.plot import express as dx

t = empty_table(50).update(
    [
        "X = i",
        "Y = Math.sin(i * 0.1) * 10",
        "Category = i % 3 == 0 ? `A` : i % 3 == 1 ? `B` : `C`",
    ]
)


def customize(fig):
    fig.update_traces(marker_line_width=2, marker_line_color="black")
    fig.add_vline(x=20, line_dash="dash", line_color="red")
    fig.add_hline(y=5, line_dash="dot", line_color="blue")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=-0.2))


dx.line(t, x="X", y="Y", by="Category", unsafe_update_figure=customize)
```

**Warnings:** do NOT remove or reorder traces (`dx` maps table columns to trace indices); add new traces at the end only; some modifications can break the figure.

Docs: `https://deephaven.io/core/plotly/docs/unsafe-update-figure.md`.
