# Data engineering conventions: official baseline + typical house rules

## 1. Source and hierarchy

There is no single official guide for data engineering. No standards body publishes a style guide for
ingestion pipelines the way PEP 8 exists for Python. What rules here are the primary documents of
the tools that execute the work, each authoritative only for its own scope: the PostgreSQL manual
for bulk loading (https://www.postgresql.org/docs/current/populate.html,
https://www.postgresql.org/docs/current/sql-copy.html), the PostGIS manual for spatial correctness
(https://postgis.net/docs/), the dbt documentation for data tests and source freshness
(https://docs.getdbt.com/), the OpenLineage specification for lineage (https://openlineage.io/docs/),
and pandera for in-process dataframe validation (https://pandera.readthedocs.io/). Where a tool's
manual speaks, it wins over habit; where none speaks, the rule is a house rule and is labeled as such.
Schema-level conventions (idempotent migrations, `ON CONFLICT` upserts, `TIMESTAMPTZ`, constraints as
invariants, isolation, `NOT VALID` constraints, deterministic `ORDER BY`) live in `sql.md` and are
not repeated here.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| `COPY` for bulk loads | "Use COPY to load all the rows in one command, instead of using a series of INSERT commands" (PostgreSQL, populate) | a loader streams with `COPY`, not a row-by-row `INSERT` loop |
| Indexes and statistics after the load | "Creating an index on pre-existing data is quicker than updating it incrementally as each row is loaded" and "running ANALYZE is strongly recommended" (PostgreSQL, populate) | build indexes after a fresh bulk load, then `ANALYZE` before the first query |
| `COPY` fails as a whole by default | "By default, COPY will fail if it encounters an error during processing" (PostgreSQL, sql-copy) | one bad row aborts the batch; `ON_ERROR ignore` is an explicit choice, never a default |
| What validity means | "Tests if an ST_Geometry value is well-formed and valid in 2D according to the OGC rules" (PostGIS, ST_IsValid) | validity is a 2D OGC property; Z and M are not checked |
| Repairing geometry | "The function attempts to create a valid representation of a given invalid geometry without losing any of the input vertices" (PostGIS, ST_MakeValid) | "attempts": the output type can change and must be checked afterwards |
| Reprojecting vs relabeling | "ST_Transform actually changes the coordinates of a geometry from one spatial reference system to another, while ST_SetSRID() simply changes the SRID identifier of the geometry" (PostGIS, ST_Transform) | `ST_SetSRID` only for data that already is in that system; otherwise `ST_Transform` |
| SRID pinned in the column type | "the SRID modifier restricts the spatial reference system SRID to a particular number" (PostGIS, using_postgis_dbmanagement) | `geometry(MultiPolygon, 25831)`, not a bare `geometry` |
| Geometry for a local area | "If your data is contained in a small area, you might find that choosing an appropriate projection and using GEOMETRY is the best solution" (PostGIS, using_postgis_dbmanagement) | city-scale data: projected `geometry`; `geography` is for global or continental extents |
| Spatial index | "GiST is the most commonly-used and versatile spatial index method" (PostGIS, using_postgis_dbmanagement) | every queried geometry column gets a GiST index |
| Tests return failures | "Data tests return a set of failing records" and "dbt ships with four generic data tests already defined: unique, not_null, accepted_values, and relationships" (dbt, data-tests) | a quality check is a query whose empty result means pass |
| Freshness has a threshold | "How old the most recent data can be before a freshness check reports an error" (dbt, freshness: `error_after`) | staleness is an error with a number, not a feeling |
| Lineage object model | "A Job is a process that consumes or produces Datasets" and "A Run is an instance of a Job that represents one of its occurrences in time" (OpenLineage, object-model) | lineage records which run of which job read and wrote which dataset |

## 3. What the official guide does NOT say

- No manual says how to tell a right upstream dataset from a wrong one with the same shape: `COPY`
  loads whatever parses, and a test on uniqueness passes on the wrong data too.
- PostgreSQL does not say how to make a load re-runnable; `COPY` appends, it does not replace a period.
- PostGIS does not pick an SRID for a project, and does not run `ST_IsValid` on insert by itself.
- `ST_MakeValid` does not promise the same geometry type or the same area; it only keeps vertices.
- dbt's four generic tests say nothing about row-count deltas between runs or value ranges.
- OpenLineage defines the event model, not which facets a project must emit or where they are stored.
- None of them define a raw/staging/curated layering, a retention policy for raw files, or backfill
  procedure: those are architecture decisions.
- pandera validates a dataframe in memory; it does not see what the database ends up holding.

## 4. Typical house rules (labeled as such)

- **Immutable raw landing**: every downloaded file is stored once, never edited, with its source URL,
  retrieval timestamp (`TIMESTAMPTZ`), byte size and SHA-256 checksum in a manifest row. Raw is the
  evidence; staging and curated are recomputable from it.
- **Three layers, one direction**: `raw` (bytes as received) -> `staging` (typed, renamed, one row
  per source record) -> `curated` (business meaning, joined, deduplicated). Curated never reads raw
  directly, and nothing writes back upstream.
- **Verify the source before trusting it**: a dataset with the right columns can be the wrong
  dataset (another indicator, another year, another territorial unit). The first load of a new
  source is checked against a published figure or a hand-verified sample, and the check is kept as a
  test. A wrong upstream dataset is a real failure mode, not a hypothetical one.
- **Idempotent loads keyed by source and period**: a re-run for the same `(source_id, period)`
  replaces that slice inside one transaction (delete-and-insert or a staging swap), so running it
  twice yields the same rows. Upsert mechanics follow `sql.md`.
- **Data contracts at stage boundaries**: each layer declares column names, types, nullability,
  units and allowed values (a pandera schema in Python, constraints in SQL). A contract change is a
  versioned change, not a silent drift.
- **Quality checks fail the load**: nulls in required columns, values outside a documented range,
  duplicate keys, a row count that moves more than a declared percentage versus the previous period,
  and freshness beyond the threshold all stop promotion to curated. A warning that nobody reads is
  not a check.
- **One SRID per table, validity checked at load**: the column type pins the SRID; staging rejects
  or repairs invalid geometries with `ST_IsValid`/`ST_MakeValid`, logs how many were repaired, and
  re-checks the geometry type afterwards. Reprojection happens once, in staging, with `ST_Transform`.
- **Lineage is recorded, not reconstructed**: each run writes job name, run id, input datasets with
  their checksums and output tables, either as OpenLineage events or a run table with the same shape.
- **Reproducible backfills**: a backfill is the normal loader run over a period range from raw,
  never a hand-written one-off script; the same input checksums produce the same curated rows.
- **No destructive reset against production**: `TRUNCATE`/`DROP` scripts run only against local or
  test databases, guarded by an explicit environment check; production recovers by re-running loads
  from raw, with a `pg_dump` taken before any schema change.
- **Secrets from the environment at the edge**: connection strings and API keys are read once in the
  entrypoint or infrastructure adapter, never in transformation code, never in a committed file.
- **Deterministic transformations**: same raw input, same curated output, byte for byte; no
  `now()` inside a transform, no unordered dedup that keeps an arbitrary row.

## 5. How it's checked

| Rule | Cheap detector | Better detector |
|---|---|---|
| Immutable raw landing | manifest row exists with URL, timestamp, checksum | re-hash raw files in CI and compare with the manifest |
| Right source | a spot check against a published figure in the change card | a pinned golden test on a known period that fails on the wrong dataset |
| Idempotent load | run the loader twice in a test, compare row counts | compare a hash of the ordered curated table after two runs |
| Contracts at boundaries | pandera schema on the staging dataframe | pandera with `lazy=True` plus SQL constraints, both in CI |
| Quality checks fail the load | dbt `unique`/`not_null`/`accepted_values`/`relationships` | row-count delta and range tests that block promotion, with a negative control |
| Freshness | `max(loaded_at)` query in the run log | dbt source freshness with `error_after` in a scheduled job |
| One SRID, valid geometry | `SELECT DISTINCT ST_SRID(geom)` and `count(*) WHERE NOT ST_IsValid(geom)` | typmod column plus a `CHECK (ST_IsValid(geom))` constraint |
| Spatial index | `\d table` shows a GiST index | `EXPLAIN` of the spatial filter shows an index scan |
| Lineage recorded | run table row per execution | OpenLineage events validated against the spec schema |
| No destructive reset in production | grep for `TRUNCATE`/`DROP` outside migrations | environment guard with a test that the script refuses a production URL |

## Sources

- https://www.postgresql.org/docs/current/populate.html
- https://www.postgresql.org/docs/current/sql-copy.html
- https://postgis.net/docs/ST_IsValid.html
- https://postgis.net/docs/ST_MakeValid.html
- https://postgis.net/docs/ST_Transform.html
- https://postgis.net/docs/using_postgis_dbmanagement.html
- https://docs.getdbt.com/docs/build/data-tests
- https://docs.getdbt.com/reference/resource-properties/freshness
- https://openlineage.io/docs/spec/object-model
- https://pandera.readthedocs.io/en/stable/

## Verdict

The tools guarantee mechanics: `COPY` loads fast and fails whole, PostGIS reprojects and repairs on
request, dbt runs the assertions you write. None of them knows whether the data is the right data.
That guarantee comes from house rules: immutable raw evidence with checksums, a verified source,
idempotent loads per period, and quality checks that stop promotion instead of logging a warning.
