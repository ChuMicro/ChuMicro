# Deephaven Time Operations Reference

## Types, Syntax, Timezones

**Types:** `Instant` (timestamp+TZ), `LocalDate`, `LocalTime`, `ZonedDateTime`, `Duration` (fixed, ISO 8601 `PT...`), `Period` (calendar `P...`).

**Duration (Instant only):** `PT1h`, `PT30m`, `PT1h30m15s`, `PT0.5s`, `PT24h`.
**Period (LocalDate only):** `P1y`, `P1m`, `P7d`, `P1y2m3d`. Period fails on Instants — use `PT24h` for a day on Instants.

**Timezones:** Full IANA (`America/New_York`, `Europe/London`, `UTC`) or aliases `ET`, `CT`, `MT`, `PT`, `UTC`, `GMT`. Three-letter Java IDs (`EST`, `CST`, `PST`) and `NY` do NOT work.

**Time constants (ns):** `SECOND`, `MINUTE`, `HOUR`, `DAY`, `WEEK`, `YEAR_365`, `YEAR_AVG`, `MILLI`, `MICRO`. Manual diff: `(Ts2 - Ts1) / HOUR`.

In query strings, time literals use backticks; LocalDate/LocalTime equality uses single quotes.

## Parsing, Creating, Filtering

Parsers: `parseInstant`, `parseLocalDate`, `parseLocalTime`, `parseZonedDateTime`. `*Quiet` variants (e.g. `parseInstantQuiet`) return null on bad input. Epoch->Instant: `epoch{Seconds,Millis,Micros,Nanos}ToInstant`. `time_table("PT1s")` builds a ticking table (optional `start_time=` ISO string).

```python
from deephaven import empty_table, time_table

ticking = time_table("PT1s")
t = empty_table(5).update(
    [
        "Ts = parseInstant(`2024-01-01T09:30:00 America/New_York`) + i * 'PT1h'",
        "D = parseLocalDate(`2024-01-0` + (i + 1))",
        "T = parseLocalTime(`09:3` + i + `:00`)",
        "Combined = toInstant(D, T, 'America/New_York')",
        "Safe = parseInstantQuiet(`bad`)",
        "Zdt = parseZonedDateTime(`2024-01-01T09:30:00 America/New_York`)",
        "FromEpoch = epochSecondsToInstant(1718454600)",
        "DPart = toLocalDate(Ts, timeZone(`America/New_York`))",
        "TPart = toLocalTime(Ts, timeZone(`America/New_York`))",
        "Now = now()",
        "TodayD = today('America/New_York')",
        "EngTZ = timeZone()",
    ]
)
t.where("Ts > parseInstant(`2024-01-01T11:00:00 America/New_York`)").where(
    ["D = '2024-01-01'", "T > '09:30:00'"]
)
```

**Non-standard formats** via `simple_date_format`. **Python datetime** via `to_j_instant` / `to_j_local_date` / `to_j_local_time`:

```python
import datetime as dt

from deephaven import new_table
from deephaven.column import string_col
from deephaven.time import (
    simple_date_format,
    to_j_instant,
    to_j_local_date,
    to_j_local_time,
)

fmt = simple_date_format("MM/dd/yyyy HH:mm:ss")
new_table([string_col("Raw", ["06/15/2024 14:30:00"])]).update(
    ["Parsed = fmt.parse(Raw).toInstant()"]
)
to_j_instant(dt.datetime(2024, 1, 15, 10, 30))
to_j_local_date(dt.date(2024, 1, 15))
to_j_local_time(dt.time(10, 30))
```

## Components, Arithmetic, Diff, Binning, Format

Extractors take `(Instant, ZoneId)`; wrap TZ IDs with `timeZone(...)`.

- **Components:** `year`, `monthOfYear`, `dayOfMonth`, `dayOfWeekValue` (1=Mon..7=Sun), `dayOfYear`, `hourOfDay(...,LST)` (0-23), `minuteOfHour`, `minuteOfDay(...,LST)` (0-1439), `secondOfMinute`, `{millis,micros,nanos}OfSecond`.
- **Diff:** `diffSeconds` / `diffMinutes` / `diffDays` / `diffNanos`.
- **Binning** (`PT24h` not `P1d` on Instants): `lowerBin`, `upperBin` (rounds up), `atMidnight(Ts, tz)`.
- **Format:** `formatDate`, `formatDateTime`, `toZonedDateTime`; `epochMillis` / `epochNanos` / `epochSeconds` / `epochMicros`. Reverse: `epoch*ToInstant(long)`.

```python
from deephaven import empty_table

tz = "timeZone(`America/New_York`)"
t = empty_table(20).update(
    [
        "Ts = parseInstant(`2024-06-15T14:30:45 America/New_York`) + i * 'PT1h'",
        "D = parseLocalDate(`2024-01-0` + ((i % 9) + 1))",
        f"Hour = hourOfDay(Ts, {tz}, true)",
        "NextMo = D + 'P1m'",  # Period on LocalDate
        "DiffMin = diffMinutes(Ts, Ts + 'PT30m')",
        "DiffHr = ((Ts + 'PT2h') - Ts) / HOUR",
        "BinDay = lowerBin(Ts, 'PT24h')",
        "BinUp = upperBin(Ts, 'PT5m')",
        f"Mid = atMidnight(Ts, {tz})",
        f"FullStr = formatDateTime(Ts, {tz})",
        f"NYTime = toZonedDateTime(Ts, {tz})",
        "EpochMs = epochMillis(Ts)",
    ]
)
```

## Business Calendar

Default calendar; no setup. `isBusinessDay`, `isBusinessTime`, `plusBusinessDays(Ts,n)`, `minusBusinessDays(Ts,n)`, `diffBusinessDays(Start,End)`.

```python
from deephaven import empty_table

t = empty_table(10).update(
    ["Ts = parseInstant(`2024-06-10T10:00:00 America/New_York`) + i * 'PT24h'"]
)
t.where("isBusinessDay(Ts)").update(
    ["NextBiz = plusBusinessDays(Ts, 1)", "IsBizTime = isBusinessTime(Ts)"]
)
```

## Patterns: OHLCV bucket + market-hours filter

```python
from deephaven import agg, empty_table

tz = "timeZone(`America/New_York`)"
t = empty_table(100).update(
    [
        "Sym = i % 2 == 0 ? `AAPL` : `GOOG`",
        "Ts = parseInstant(`2024-01-01T09:30:00 America/New_York`) + i * 'PT10s'",
        "Price = 150.0 + Math.sin(i * 0.1) * 10",
        "Qty = (int)(100 + i * 10)",
        "Bucket = lowerBin(Ts, 'PT1m')",
    ]
)
ohlcv = t.agg_by(
    [
        agg.first(["O=Price"]),
        agg.max_(["H=Price"]),
        agg.min_(["L=Price"]),
        agg.last(["C=Price"]),
        agg.sum_(["V=Qty"]),
    ],
    by=["Sym", "Bucket"],
)
mkt = t.where([f"hourOfDay(Ts,{tz},true) >= 9", f"hourOfDay(Ts,{tz},true) < 16"])
```
