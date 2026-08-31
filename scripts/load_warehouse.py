"""Append crawl output to the bi_governance schema in the warehouse.

Supports BigQuery and Snowflake. Appends (never truncates) so snapshots
accumulate and trends are queryable.

BigQuery:
    GOOGLE_APPLICATION_CREDENTIALS=sa.json \
    python load_warehouse.py --target bigquery --project <proj> --dataset bi_governance

Snowflake:
    SNOWFLAKE_ACCOUNT=... SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=... \
    python load_warehouse.py --target snowflake --database <db> --schema BI_GOVERNANCE
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

TABLES = {
    "lineage": "out/lineage.csv",
    "dashboard_similarity": "out/dashboard_similarity.csv",
}


def load_bigquery(project: str, dataset: str) -> None:
    for table, path in TABLES.items():
        df = pd.read_csv(path)
        df.to_gbq(f"{dataset}.{table}", project_id=project, if_exists="append")
        print(f"Appended {len(df)} rows to {project}.{dataset}.{table}")


def load_snowflake(database: str, schema: str) -> None:
    import snowflake.connector
    from snowflake.connector.pandas_tools import write_pandas

    database, schema = database.upper(), schema.upper()
    warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH").upper()

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
    )
    cur = conn.cursor()
    cur.execute(f'use warehouse "{warehouse}"')
    cur.execute(f'create schema if not exists "{database}"."{schema}"')
    cur.execute(f'use schema "{database}"."{schema}"')

    for table, path in TABLES.items():
        df = pd.read_csv(path)
        df.columns = [c.upper() for c in df.columns]
        write_pandas(conn, df, table.upper(),
                     database=database, schema=schema, auto_create_table=True)
        print(f"Appended {len(df)} rows to {database}.{schema}.{table.upper()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["bigquery", "snowflake"])
    parser.add_argument("--project")
    parser.add_argument("--dataset", default="bi_governance")
    parser.add_argument("--database")
    parser.add_argument("--schema", default="BI_GOVERNANCE")
    args = parser.parse_args()

    for path in TABLES.values():
        if not os.path.exists(path):
            sys.exit(f"Missing {path} - run crawl.py and similarity.py first.")

    if args.target == "bigquery":
        if not args.project:
            sys.exit("--project is required for BigQuery.")
        load_bigquery(args.project, args.dataset)
    else:
        if not args.database:
            sys.exit("--database is required for Snowflake.")
        load_snowflake(args.database, args.schema)


if __name__ == "__main__":
    main()
