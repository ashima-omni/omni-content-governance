# omni-content-governance

Content traceability and dashboard governance for [Omni](https://omni.co), built on the Omni REST API.

Dashboard sprawl happens when finding an existing answer costs more than building a new dashboard. This repo makes the finding cheap: it crawls an Omni instance into a lineage dataset (document > tile > topic > view > field), scores every pair of dashboards for duplication, lands both as warehouse tables, and models them back in Omni - so "these two dashboards are 0.85 similar, merge them" is a tile on a dashboard, not a hunch.

The full write-up lives in [docs/content-traceability-and-governance.md](docs/content-traceability-and-governance.md): the API building blocks, query-view traceability, the governance standards, and the automation cadence.

## What's here

```
docs/      The guide (traceability, query views, governance standards, cadence)
scripts/   crawl.py - documents/tiles -> lineage.csv
           similarity.py - pairwise Jaccard scores -> dashboard_similarity.csv
           find_view_usage.py - "which dashboards use view X" (content-validator)
           load_warehouse.py - append snapshots to BigQuery or Snowflake
sql/       DDL for the bi_governance schema + the governance queries
omni/      View and topic YAML to model bi_governance in Omni
.github/   Scheduled workflow to run the pipeline nightly
```

## Quick start

```bash
pip install -r requirements.txt

export OMNI_BASE_URL=https://your-org.omniapp.co
export OMNI_TOKEN=<api key>          # Settings > API keys

python scripts/crawl.py              # -> out/lineage.csv
python scripts/similarity.py         # -> out/dashboard_similarity.csv

# Blast radius before touching a view:
python scripts/find_view_usage.py --model-id <uuid> --find users_facts --type VIEW
```

Then land the snapshots and model them:

1. Create the schema: `sql/bi_governance_ddl.sql`
2. Load: `python scripts/load_warehouse.py --target bigquery --project <p>` (or `--target snowflake --database <db>`)
3. In Omni: refresh the connection's schema, add the views and topic from `omni/`, and build the governance dashboard from `sql/governance_queries.sql`

## Thresholds

Similarity is Jaccard overlap of tile-query hashes. Defaults: `1.0` = exact duplicate, `>= 0.7` = merge candidate. Tune them in `scripts/similarity.py` after your first month of reviewing what they surface.

## Automation

`.github/workflows/governance.yml` runs crawl > similarity > load nightly. Set `OMNI_BASE_URL`, `OMNI_TOKEN`, and warehouse credentials as repository secrets. Recommended cadence, from the guide: nightly snapshots, weekly duplicate and query-view digests, monthly stale-content sweep with a 30-day grace period, quarterly estate review.

## Notes

- The document-queries endpoint is rate limited (~60 req/min); `crawl.py` backs off automatically.
- Loads append rather than truncate - the history is what makes trends queryable.
- Omni's built-in Analytics (admin) already covers usage; this repo adds the lineage and duplication layer. See the guide for the split.
