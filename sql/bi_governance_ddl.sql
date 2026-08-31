-- bi_governance schema: content lineage + dashboard similarity snapshots.
-- Generic SQL; adjust types for your warehouse (BigQuery: use DATE/STRING/INT64/FLOAT64/TIMESTAMP).

create schema if not exists bi_governance;

create table if not exists bi_governance.lineage (
  snapshot_date  date,
  doc_id         varchar,
  document       varchar,
  folder_path    varchar,
  owner_name     varchar,
  doc_views      integer,      -- _count.views from the Documents API
  doc_favorites  integer,
  updated_at     timestamp,
  tile           varchar,
  tile_url       varchar,
  tile_hash      varchar,      -- sha256 of the query's analytical core
  topic          varchar,
  view_name      varchar,
  field_name     varchar,      -- one row per field
  model_id       varchar
);

create table if not exists bi_governance.dashboard_similarity (
  snapshot_date  date,
  doc_id_a       varchar,
  doc_name_a     varchar,
  doc_id_b       varchar,
  doc_name_b     varchar,
  shared_tiles   integer,
  tiles_a        integer,
  tiles_b        integer,
  similarity     float,        -- Jaccard on tile hashes, 0 to 1
  verdict        varchar       -- 'exact_duplicate' | 'merge_candidate' | 'ok'
);
