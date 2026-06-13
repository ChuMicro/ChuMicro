# Deephaven UI Dashboard Development

`deephaven.ui` is React-like: state changes trigger re-renders; UI is a function of state. Docs: `https://deephaven.io/core/ui/docs/{components,hooks}/<name>.md`.

## Components & Hooks

```python
from deephaven import ui


@ui.component
def my_component():
    return ui.text("Content")


result = my_component()
```

**Hook rules:** call hooks only at the top level of `@ui.component` or custom hooks — never inside loops, conditions, or nested functions.

- `use_state` — state that triggers re-renders. `use_memo` — cache expensive computations and tables created in components. `use_callback` — cache function defs. `use_effect` — side effects. `use_ref` — mutable ref (no re-render).
- `use_table_data` / `use_column_data` / `use_row_data` / `use_row_list` / `use_cell_data` — read table contents (full / column-as-list / row-as-dict / row-as-list / cell).
- `use_table_listener` — listen for table updates. `use_liveness_scope` — manage table lifecycle in state. `use_render_queue` — thread-safe state updates.

## Dashboard Structure

Hierarchy: `ui.dashboard` → exactly one `row`/`column` → alternating `column`/`row` → optional `ui.stack` (tabs) → `ui.panel` (content).

**Rules:**
- `ui.dashboard` lives at script root, **never inside `@ui.component`**, with exactly one child.
- Rows and columns alternate. Use `height` on rows and `width` on columns/stacks as proportional values (e.g. `height=25` / `height=75`).
- `ui.panel` may only be a child of row/column/stack — **never nest row/column/stack/panel inside a panel**.
- Panels are flex-column by default; no need to wrap content in `ui.flex`.
- One panel per interacting component (panels share state via the parent component).
- For tabs, put `ui.stack` directly in a row/column with `ui.panel`s as children.

**Stateful dashboards:** return `ui.row`/`ui.column` from a component and wrap with `ui.dashboard(comp())`. State owned by the parent component is shared across panels via props/callbacks — see the picker example below. Always use this layout, since any dashboard may grow stateful.

## Available Components

- **Layout:** `dashboard`, `row`, `column`, `stack`, `panel`, `flex`, `grid`, `fragment`, `view`, `divider`, `tabs`, `accordion`, `disclosure`, `form`
- **Inputs:** `text_field`, `text_area`, `number_field`, `checkbox`, `checkbox_group`, `radio_group`, `switch`, `slider`, `range_slider`, `picker`, `combo_box`, `date_picker`, `date_field`, `date_range_picker`, `time_field`, `search_field`, `toggle_button`
- **Actions:** `button`, `action_button`, `action_group`, `action_menu`, `button_group`, `menu_trigger`, `dialog_trigger`, `link`
- **Display:** `text`, `heading`, `markdown`, `badge`, `meter`, `progress_bar`, `progress_circle`, `illustrated_message`, `inline_alert`, `toast`, `icon`, `image`, `tag_group`, `labeled_value`
- **Data:** `table`, `list_view`
- **Overlays:** `dialog`, `contextual_help`

## Selection: picker / combo_box / list_view

Pick from a set. `picker` (dropdown) is default; `combo_box` adds search/free-text; `list_view` is always-visible multi-select. All share `on_selection_change`.

**Table-backed (preferred):** pass a Table — first column is both key and label.
- **Always `select_distinct`** — duplicate keys raise.
- **Keys must be strings** — numeric columns silently produce zero options. Cast: `.update_view(["Col = `` + Col"])`.
- Custom mapping: `ui.item_table_source(table, key_column="Id", label_column="Name")`.
- `selected_key=None` ⇒ "show all" — filter with `t if selected is None else t.where(...)`.

**Static options (`ui.item()` per option):** only when choices are fixed in code, or to inject extras like "All". For an "All" entry: `selected, set_selected = ui.use_state(None)` → `ui.picker(ui.item("All", key="All"), ui.item("A"), ..., selected_key=selected or "All", on_selection_change=lambda v: set_selected(None if v == "All" else v))`.

**Do NOT mix `ui.item()` with a Table in the same picker** — items are silently dropped. To combine, materialize with `use_column_data`: `ui.picker(ui.item("All", key="All"), *[ui.item(v) for v in ui.use_column_data(t, "Sym")], ...)`.

```python
from deephaven import empty_table, ui
from deephaven.plot import express as dx

source = empty_table(4).update(["Sym=`AAPL`", "Date=i", "Price=1.0*i"])


@ui.component
def filtered_dashboard(t):
    sel, set_sel = ui.use_state("AAPL")
    picker = ui.picker(
        t.select_distinct(["Sym"]),
        label="Symbol",
        selected_key=sel,
        on_selection_change=set_sel,
    )
    filtered = ui.use_memo(lambda: t.where(f"Sym = `{sel}`"), [sel])
    chart = ui.use_memo(lambda: dx.line(filtered, x="Date", y="Price"), [filtered])
    return ui.column(
        ui.row(ui.panel(picker, title="Filters"), height=15),
        ui.row(
            ui.panel(chart, title="Chart"),
            ui.panel(ui.table(filtered), title="Data"),
            height=85,
        ),
    )


dashboard = ui.dashboard(filtered_dashboard(source))
```

## Buttons & Icons

| Component | Use For |
|-----------|---------|
| `button` | Primary actions (`variant="accent"` for emphasis) |
| `action_button` | Secondary / icon-only (`is_quiet=True`) |
| `toggle_button` | Binary on/off |

Icons: lowercase names (`account`, `filter`, `arrow_left`) — see `https://deephaven.io/core/ui/docs/components/icon.md`.

## ui.flex

CSS flexbox for grouping inside panels. Props: `direction` (`row`/`column`[-reverse]), `wrap`, `gap`/`column_gap`/`row_gap`, `justify_content` (`start`/`end`/`center`/`space-between`/`space-around`/`space-evenly`), `align_items` (`start`/`end`/`center`/`stretch`/`baseline`). Example: `ui.flex(a, b, direction="row", gap="size-200", align_items="center")`.

## Sizing & Colors

- **Size tokens:** `size-100`–`size-300` common (range `size-0`–`size-6000`).
- **Semantic colors (preferred):** `positive`, `negative`, `notice`, `info`, `accent`.
- **Palette:** `{name}-{100..1400}` for `red`, `orange`, `yellow`, `chartreuse`, `celery`, `green`, `seafoam`, `cyan`, `blue`, `indigo`, `purple`, `fuchsia`, `magenta`. Auto-adapts to light/dark theme.
- **Gray:** `gray-50`–`gray-900`. **Raw:** hex or CSS names. Use as `background_color="blue-600"`, `border_color="accent"`.

## ui.table

Wraps a Deephaven table for custom display/interactivity. **Only use when you need its features** — plain tables render fine without it. The table arg is the only required prop.

```python
from deephaven import empty_table, ui

t = empty_table(4).update(
    ["Sym=`AAPL`", "Exchange=`NYSE`", "Price=1.0", "Qty=1", "Total=1.0"]
)

ui.table(
    t,
    # Column layout
    front_columns=["Sym"],
    back_columns=["Exchange"],
    frozen_columns=["Sym"],
    hidden_columns=["Total"],
    column_display_names={"Sym": "Symbol"},
    reverse=True,  # reverse useful for ticking
    # Formatting (cols+value pattern, or if_+style)
    format_=[
        ui.TableFormat(cols="Price", value="$#,##0.00"),
        ui.TableFormat(if_="Price > 145", background_color="positive"),
    ],
    # Filters
    show_quick_filters=True,
    quick_filters={"Sym": "AAPL", "Price": ">=100"},
    # Aggregations row
    aggregations=[ui.TableAgg(agg="Sum", cols=["Qty"]), ui.TableAgg(agg="Count")],
    aggregations_position="top",  # or "bottom"
    # Menus + events
    context_menu=[{"title": "View", "action": lambda data: print(data)}],
    context_header_menu=[{"title": "Sort", "action": lambda col: print(col)}],
    on_row_press=lambda row: print(row),
    always_fetch_columns=["Sym", "Price"],  # ensure data in callbacks
)
```

**Tables in state:** tables created inside a component must be wrapped in `use_memo` so they're reused across renders, e.g. `table = ui.use_memo(lambda: time_table("PT1s"), [reset_count])`.
