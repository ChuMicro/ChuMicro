# Deephaven Iceberg Integration Reference

Apache Iceberg is a high-performance table format. Module: `deephaven.experimental.iceberg` (API may change). Some catalog types need extra classpath deps.

**Supported catalogs:** REST, AWS Glue, JDBC, Hive, Hadoop, Nessie.

## Catalog Adapters

All adapter constructors connect to the catalog, so the examples below need a real backend.

```python
# pseudo  (real Iceberg catalog required)
from deephaven.experimental import iceberg

# Generic (any catalog type via properties)
adapter = iceberg.adapter(
    name="my-catalog",
    properties={
        "type": "rest",  # or "glue", "hive", "hadoop", "nessie", "jdbc"
        "uri": "http://iceberg-rest:8181",
        "warehouse": "s3://my-bucket/warehouse",
        "s3.access-key-id": "my-access-key",
        "s3.secret-access-key": "my-secret-key",
        "s3.endpoint": "http://minio:9000",
        "s3.region": "us-east-1",
        "io-impl": "org.apache.iceberg.aws.s3.S3FileIO",
    },
)

# S3-backed REST shortcut
adapter = iceberg.adapter_s3_rest(
    name="s3-catalog",
    catalog_uri="http://iceberg-rest:8181",
    warehouse_location="s3://bucket/warehouse",
    region_name="us-east-1",
    access_key_id="my-access-key",
    secret_access_key="my-secret-key",
    end_point_override="http://minio:9000",  # optional, MinIO/LocalStack
)

# AWS Glue shortcut
adapter = iceberg.adapter_aws_glue(
    name="glue-catalog",
    region_name="us-east-1",
    access_key_id="my-access-key",
    secret_access_key="my-secret-key",
)
```

## Exploring & Reading

```python
# pseudo  (real catalog required)
from deephaven.experimental import iceberg

adapter = iceberg.adapter(name="c", properties={"type": "rest", "uri": "http://iceberg-rest:8181"})

namespaces = adapter.namespaces()
tables = adapter.tables(namespace="my_namespace")
table_adapter = adapter.load_table("namespace.table_name")

# Read modes
t = table_adapter.table(update_mode=iceberg.IcebergUpdateMode.static())          # snapshot at read
t = table_adapter.table(update_mode=iceberg.IcebergUpdateMode.manual_refresh())  # call refresh()
table_adapter.refresh()
t = table_adapter.table(update_mode=iceberg.IcebergUpdateMode.auto_refresh())    # default 60s
t = table_adapter.table(update_mode=iceberg.IcebergUpdateMode.auto_refresh(auto_refresh_ms=30000))
```

## Read Instructions & Resolvers

```python
from deephaven import dtypes as dht
from deephaven.experimental import iceberg

# Specific snapshot
instructions = iceberg.IcebergReadInstructions(snapshot_id=6738371110677246500)

# Field-ID-based resolution (preferred for renames / typed schemas)
resolver = iceberg.UnboundResolver(
    table_definition={"Symbol": dht.string, "Price": dht.double, "Qty": dht.int64},
    column_instructions={"Symbol": 1, "Price": 2, "Qty": 3},  # name -> Iceberg field ID
)
```

**Note:** the `column_renames=` and `table_definition=` kwargs on `IcebergReadInstructions` are deprecated and have no effect. Use `UnboundResolver` instead.

## Writing Tables

Deephaven supports **append-only** writes (no updates/deletes). Tables passed together must share an identical schema.

```python
# pseudo  (real catalog required)
from deephaven import empty_table
from deephaven.experimental import iceberg

source = empty_table(100).update([
    "ID = ii",
    "Value = randomDouble(0, 100)",
    "Category = (ii % 3 == 0) ? `A` : (ii % 3 == 1) ? `B` : `C`",
])

adapter = iceberg.adapter(name="c", properties={"type": "rest", "uri": "http://iceberg-rest:8181"})

# Create new table from a definition
table_adapter = adapter.create_table(
    table_identifier="namespace.new_table",
    table_definition=source.definition,
)

# Or load an existing one
table_adapter = adapter.load_table("namespace.existing_table")

# Write / append (multiple tables OK if same schema)
writer_options = iceberg.TableParquetWriterOptions(table_definition=source.definition)
writer = table_adapter.table_writer(writer_options=writer_options)
writer.append(iceberg.IcebergWriteInstructions([source]))
```

`TableParquetWriterOptions` and `IcebergWriteInstructions` are constructible without a catalog:

```python
from deephaven import empty_table
from deephaven.experimental import iceberg

source = empty_table(10).update(["ID = ii", "Value = (double)ii"])
writer_options = iceberg.TableParquetWriterOptions(table_definition=source.definition)
write_instr = iceberg.IcebergWriteInstructions([source])
```

### Partitioned Writes

Partitioning columns come from the partition path, **not** the data — they must not appear in the source table.

```python
from deephaven import dtypes as dht
from deephaven.column import ColumnType, col_def

partitioned_def = [
    col_def("Year", dht.int32, column_type=ColumnType.PARTITIONING),
    col_def("ID", dht.int64),
    col_def("Value", dht.double),
]
```

## S3 Configuration

```python
from deephaven.experimental import s3

s3_instructions = s3.S3Instructions(
    region_name="us-east-1",
    endpoint_override="http://minio:9000",  # MinIO/LocalStack
)
```

Prefer `Credentials.basic(access_key_id, secret_access_key)` over the deprecated `access_key_id=` / `secret_access_key=` kwargs.

## Common Patterns

```python
# pseudo  (real catalog required)
from deephaven import agg
from deephaven.experimental import iceberg

adapter = iceberg.adapter_s3_rest(
    name="s3-catalog",
    catalog_uri="http://iceberg-rest:8181",
    warehouse_location="s3://bucket/warehouse",
    region_name="us-east-1",
    access_key_id="k", secret_access_key="s",
)

# Read -> aggregate -> write back
raw = adapter.load_table("ns.raw_data").table(update_mode=iceberg.IcebergUpdateMode.static())
aggregated = raw.agg_by(
    [agg.sum_(cols=["TotalValue = Value"]), agg.count_(col="Count")],
    by=["Category"],
)
result = adapter.create_table("ns.aggregated_data", aggregated.definition)
result.table_writer(
    writer_options=iceberg.TableParquetWriterOptions(table_definition=aggregated.definition)
).append(iceberg.IcebergWriteInstructions([aggregated]))

# Auto-refreshing live dashboard table
live = adapter.load_table("ns.events").table(
    update_mode=iceberg.IcebergUpdateMode.auto_refresh(auto_refresh_ms=30000)
)
latest = live.last_by("EventType")
```

## Key Constraints

1. **Append-only** — no updates/deletes.
2. **Same schema** for tables written together.
3. **Partition columns not in data** — values come from partition path.
4. **Experimental** — `deephaven.experimental.iceberg` API may change.

## Documentation URLs

- Overview: https://deephaven.io/core/docs/how-to-guides/data-import-export/iceberg.md
- Reference index: https://deephaven.io/core/docs/reference/iceberg/
  (`adapter`, `adapter-s3-rest`, `adapter-aws-glue`, `iceberg-read-instructions`, `iceberg-write-instructions`, `iceberg-update-mode`)
