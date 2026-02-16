#!/usr/bin/env python3
"""
Print all tag keys and distinct infrastructure types (amenity, building, landuse, industrial)
from the OSM Athena table. Writes full output to a file (default: osm_tags_and_infra.txt).
Uses the same env vars as the MCP server: ATHENA_DB, ATHENA_OUTPUT, AWS_REGION, ATHENA_OSM_TABLE.

Usage:
  cd services/mcp_server && python scripts/list_osm_tags_and_infra.py
  python scripts/list_osm_tags_and_infra.py --output my_results.txt
  ATHENA_DB=osm ATHENA_OUTPUT=s3://your-bucket/ AWS_REGION=eu-west-3 python scripts/list_osm_tags_and_infra.py
"""

import argparse
import os
import sys
import time

try:
    import boto3
except ImportError:
    print("Install boto3: pip install boto3", file=sys.stderr)
    sys.exit(1)


def get_config():
    athena_db = os.environ.get("ATHENA_DB", "default")
    athena_output = os.environ.get("ATHENA_OUTPUT", "s3://metaplanet-athena-query-results-963275461308/")
    region = os.environ.get("AWS_REGION", "us-east-1")
    table = os.environ.get("ATHENA_OSM_TABLE", "planet")
    if not athena_output.strip():
        print("Set ATHENA_OUTPUT (S3 URI for query results).", file=sys.stderr)
        sys.exit(1)
    return athena_db, athena_output.rstrip("/") + "/", region, table


def run_query(client, database: str, query: str, output_location: str) -> list[dict]:
    """Start query, wait for completion, return ALL result rows (paginated)."""
    resp = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output_location},
    )
    qid = resp["QueryExecutionId"]
    while True:
        out = client.get_query_execution(QueryExecutionId=qid)
        state = out["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            if state != "SUCCEEDED":
                reason = out["QueryExecution"]["Status"].get("StateChangeReason", "")
                raise RuntimeError(f"Query {state}: {reason}")
            break
        time.sleep(1)
    header = None
    out_rows = []
    next_token = None
    while True:
        kwargs = {"QueryExecutionId": qid, "MaxResults": 1000}
        if next_token:
            kwargs["NextToken"] = next_token
        results = client.get_query_results(**kwargs)
        rows = results["ResultSet"]["Rows"]
        if not rows:
            break
        if header is None:
            header = [c.get("VarCharValue", "").strip() for c in rows[0]["Data"]]
            rows = rows[1:]
        for r in rows:
            out_rows.append({
                header[i]: (r["Data"][i].get("VarCharValue", "") if i < len(r["Data"]) else "")
                for i in range(len(header))
            })
        next_token = results.get("NextToken")
        if not next_token:
            break
    return out_rows


def main():
    parser = argparse.ArgumentParser(description="List all OSM tag keys and infra types to a file.")
    parser.add_argument(
        "--output", "-o",
        default=os.environ.get("OUTPUT_FILE", "osm_tags_and_infra.txt"),
        help="Output file path (default: osm_tags_and_infra.txt or OUTPUT_FILE env)",
    )
    args = parser.parse_args()
    out_path = args.output

    athena_db, athena_output, region, table = get_config()
    client = boto3.client("athena", region_name=region)

    def write(f, s=""):
        f.write(s + "\n")
        f.flush()

    with open(out_path, "w", encoding="utf-8") as f:
        write(f, f"Database: {athena_db}, Table: {table}, Region: {region}")
        write(f)

        # 1) All distinct tag keys (no limit)
        write(f, "=" * 60)
        write(f, "ALL DISTINCT TAG KEYS")
        write(f, "=" * 60)
        try:
            rows = run_query(
                client,
                athena_db,
                f"""
                SELECT key FROM (
                    SELECT DISTINCT key
                    FROM {table}
                    CROSS JOIN UNNEST(map_keys(tags)) AS t(key)
                )
                ORDER BY key
                """,
                athena_output,
            )
            for row in rows:
                write(f, row.get("key", ""))
            write(f, f"\nTotal tag keys: {len(rows)}")
            write(f)
        except Exception as e:
            write(f, f"Error: {e}")
            write(f)

        # 2) Distinct values for infrastructure-related keys (no limit)
        for tag_key in ("amenity", "building", "landuse", "industrial"):
            write(f, "=" * 60)
            write(f, f"INFRA TYPE: tags['{tag_key}'] (distinct values with count)")
            write(f, "=" * 60)
            try:
                rows = run_query(
                    client,
                    athena_db,
                    f"""
                    SELECT tags['{tag_key}'] as value, COUNT(*) as cnt
                    FROM {table}
                    WHERE tags['{tag_key}'] IS NOT NULL
                    GROUP BY tags['{tag_key}']
                    ORDER BY cnt DESC
                    """,
                    athena_output,
                )
                for row in rows:
                    write(f, f"  {row.get('value', '')}  ({row.get('cnt', '')})")
                write(f, f"\nTotal values: {len(rows)}")
                write(f)
            except Exception as e:
                write(f, f"Error: {e}")
                write(f)

        write(f, "Done.")

    print(f"Results written to {out_path}")


if __name__ == "__main__":
    main()
