# Deephaven Kafka Reference

Consume Kafka topics as real-time tables; produce table changes back to Kafka.

## Basic Consumption

```python
# pseudo
from deephaven.stream.kafka import consumer as kc
from deephaven import dtypes as dht

result = kc.consume(
    {"bootstrap.servers": "kafka:9092"}, "topic.name",
    key_spec=kc.KeyValueSpec.IGNORE,
    value_spec=kc.simple_spec("Value", dht.string),
    table_type=kc.TableType.append(),
)
```

## Table Types

- `TableType.append()` — all rows (unbounded); full history
- `TableType.blink()` — current cycle only (default); stateful aggs
- `TableType.ring(N)` — last N rows; bounded memory

```python
from deephaven.stream.kafka import consumer as kc

types = (kc.TableType.append(), kc.TableType.blink(), kc.TableType.ring(1000))
```

## Standard Columns

Every consumed table has `KafkaPartition` (int), `KafkaOffset` (long), `KafkaTimestamp` (Instant). Disable any by setting its `deephaven.{partition,offset,timestamp}.column.name` property to `""`.

## Key and Value Specs

```python
from deephaven import dtypes as dht
from deephaven.stream.kafka import consumer as kc

# Ignore key or value
ignore_spec = kc.KeyValueSpec.IGNORE

# Simple types: string, int32, int64, double, bool_, etc.
v_str = kc.simple_spec("Value", dht.string)
v_int = kc.simple_spec("IntCol", dht.int32)
v_long = kc.simple_spec("LongCol", dht.int64)
v_dbl = kc.simple_spec("DoubleCol", dht.double)
v_bool = kc.simple_spec("BoolCol", dht.bool_)

# JSON: col_defs (required), mapping (optional JSON-field -> column rename;
# leading '/' = JSON Pointer for nested fields)
v_json = kc.json_spec(
    col_defs={
        "Symbol": dht.string,
        "Price": dht.double,
        "Qty": dht.int64,
        "Timestamp": dht.Instant,
    },
    mapping={"sym": "Symbol", "px": "Price", "qty": "Qty", "ts": "Timestamp"},
)

# Avro: schema (registry name or JSON), schema_version (default "latest"),
# mapping (avro-field -> column), mapped_only (drop unmapped fields)
v_avro = kc.avro_spec(
    schema="record.name",
    schema_version="1",
    # mapping={"field1": "Col1"}, mapped_only=False,
)

# Protobuf: schema (registry subject), schema_version (int, None=latest),
# schema_message_name (FQN to pick inner message), include (path filters),
# message_class (use classpath instead of registry), protocol
v_pb = kc.protobuf_spec(
    schema="message.subject",
    schema_version=1,
    # schema_message_name="com.example.MyMessage",
)
```

For Avro/Protobuf via schema registry, properties must include `"schema.registry.url"`. For raw bytes, use `kc.object_processor_spec` (e.g. with `dht.byte_array`).

## Complete Examples

```python
# pseudo
from deephaven.stream.kafka import consumer as kc
from deephaven import dtypes as dht

# JSON consumer
trades = kc.consume(
    {"bootstrap.servers": "kafka:9092"}, "trades",
    key_spec=kc.simple_spec("Symbol", dht.string),
    value_spec=kc.json_spec({"Price": dht.double, "Quantity": dht.int64, "Timestamp": dht.Instant, "Side": dht.string}),
    table_type=kc.TableType.append(),
)

# Avro consumer (needs schema.registry.url)
quotes = kc.consume(
    {"bootstrap.servers": "kafka:9092", "schema.registry.url": "http://schema-registry:8081"},
    "quotes",
    key_spec=kc.KeyValueSpec.IGNORE,
    value_spec=kc.avro_spec("quote.record", schema_version="latest"),
    table_type=kc.TableType.blink(),
)

# Partitioned (by Kafka partition); merge() to flatten
partitioned = kc.consume_to_partitioned_table(
    {"bootstrap.servers": "kafka:9092"}, "topic.name",
    key_spec=kc.KeyValueSpec.IGNORE,
    value_spec=kc.simple_spec("Value", dht.string),
    table_type=kc.TableType.append(),
)
merged = partitioned.merge()
```

## Offset Control

Pass `offsets=` to `kc.consume`: `kc.ALL_PARTITIONS_SEEK_TO_BEGINNING`, `kc.ALL_PARTITIONS_SEEK_TO_END`, or a per-partition dict like `{0: 100, 1: 200}`.

```python
from deephaven.stream.kafka import consumer as kc

beg = kc.ALL_PARTITIONS_SEEK_TO_BEGINNING
end = kc.ALL_PARTITIONS_SEEK_TO_END
specific = {0: 100, 1: 200}
```

## Producing to Kafka

`pk.produce(source, kafka_config, topic, key_spec=..., value_spec=...)`. Specs:
- `pk.simple_spec(col_name)`
- `pk.json_spec(include_columns=, exclude_columns=, mapping=, nested_delim=, output_nulls=, timestamp_field=)`
- `pk.avro_spec(schema, schema_version="latest", field_to_col_mapping=, timestamp_field=, include_only_columns=, exclude_columns=, publish_schema=, schema_namespace=, column_properties=)`

```python
# pseudo
from deephaven.stream.kafka import producer as pk
from deephaven import time_table

src = time_table("PT1s").update(["Col1 = ii", "Col2 = ii * 2"])
props = {"bootstrap.servers": "kafka:9092"}
avro_props = {**props, "schema.registry.url": "http://sr:8081"}

pk.produce(src, props, "out", key_spec=pk.KeyValueSpec.IGNORE,
           value_spec=pk.simple_spec("Col1"))
pk.produce(src, props, "out", key_spec=pk.KeyValueSpec.IGNORE,
           value_spec=pk.json_spec(include_columns=["Col1", "Col2"],
                                   timestamp_field="Ts"))
pk.produce(src, avro_props, "out", key_spec=pk.KeyValueSpec.IGNORE,
           value_spec=pk.avro_spec("out.record",
                                   include_only_columns=["Col1", "Col2"]))
```

## Common Patterns

Trades -> 1m OHLCV; join blink streams via `blink_to_append_only`:
```python
# pseudo
from deephaven.stream.kafka import consumer as kc
from deephaven import dtypes as dht, agg
from deephaven.stream import blink_to_append_only

props = {"bootstrap.servers": "kafka:9092"}
trades = kc.consume(props, "trades",
    key_spec=kc.simple_spec("Symbol", dht.string),
    value_spec=kc.json_spec({"Price": dht.double, "Qty": dht.int64, "Timestamp": dht.Instant}),
    table_type=kc.TableType.blink())
quotes = kc.consume(props, "quotes",
    key_spec=kc.simple_spec("Symbol", dht.string),
    value_spec=kc.json_spec({"Bid": dht.double, "Ask": dht.double, "Timestamp": dht.Instant}),
    table_type=kc.TableType.blink())

ohlcv = trades.update(["TimeBucket = lowerBin(Timestamp, 'PT1m')"]).agg_by([
    agg.first(cols=["Open = Price"]), agg.max_(cols=["High = Price"]),
    agg.min_(cols=["Low = Price"]), agg.last(cols=["Close = Price"]),
    agg.sum_(cols=["Volume = Qty"]),
], by=["Symbol", "TimeBucket"])

enriched = blink_to_append_only(trades).aj(blink_to_append_only(quotes),
                                           on=["Symbol", "Timestamp"])
```

## Properties Reference

```python
properties = {
    "bootstrap.servers": "kafka:9092",
    "schema.registry.url": "http://registry:8081",  # Avro/Protobuf
    "group.id": "my-consumer-group",
    "auto.offset.reset": "earliest",  # or "latest"
    # Security
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "PLAIN",
    "sasl.jaas.config": "...",
    # Deephaven-specific (set to "" to disable column)
    "deephaven.partition.column.name": "KafkaPartition",
    "deephaven.offset.column.name": "KafkaOffset",
    "deephaven.timestamp.column.name": "KafkaTimestamp",
}
```

## Docs

- https://deephaven.io/core/docs/how-to-guides/data-import-export/kafka-stream.md
- https://deephaven.io/core/docs/reference/data-import-export/Kafka/consume.md
- https://deephaven.io/core/docs/reference/data-import-export/Kafka/produce.md
