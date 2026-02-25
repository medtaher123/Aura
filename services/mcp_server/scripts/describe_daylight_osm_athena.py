#!/usr/bin/env python3
"""
Print the columns (schema) of the Daylight OSM table in Athena.

Uses DAYLIGHT_ATHENA_OUTPUT (or config default) and us-west-2.
Bucket must be in us-west-2.

Usage:
  cd services/mcp_server && python scripts/describe_daylight_osm_athena.py
  DAYLIGHT_ATHENA_OUTPUT=s3://your-bucket-in-us-west-2/ python scripts/describe_daylight_osm_athena.py
"""

import os
import sys
import time

# Add parent so we can import config when run from repo root or mcp_server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Install boto3: pip install boto3", file=sys.stderr)
    sys.exit(1)


def main():
    try:
        from config import get_config
        cfg = get_config()
        athena_output = (cfg.daylight_athena_output or os.environ.get("DAYLIGHT_ATHENA_OUTPUT") or "").strip()
        athena_db = os.environ.get("ATHENA_DB") or cfg.athena_db or "default"
    except Exception:
        athena_output = os.environ.get("DAYLIGHT_ATHENA_OUTPUT", "").strip()
        athena_db = os.environ.get("ATHENA_DB", "default")

    if not athena_output or athena_output.startswith("s3://your-"):
        print("Set DAYLIGHT_ATHENA_OUTPUT to an S3 URI in us-west-2 (e.g. s3://your-bucket/).", file=sys.stderr)
        sys.exit(1)

    region = "us-west-2"
    output_location = athena_output.rstrip("/") + "/"

    client = boto3.client("athena", region_name=region)

    # DESCRIBE returns: col_name, data_type, comment (in Athena/Presto)
    query = "DESCRIBE daylight_osm_features"
    print(f"Database: {athena_db}")
    print(f"Region: {region}")
    print(f"Query: {query}\n")

    try:
        resp = client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": athena_db},
            ResultConfiguration={"OutputLocation": output_location},
        )
        qid = resp["QueryExecutionId"]
    except ClientError as e:
        print(f"StartQueryExecution failed: {e}", file=sys.stderr)
        sys.exit(1)

    while True:
        out = client.get_query_execution(QueryExecutionId=qid)
        state = out["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = out["QueryExecution"]["Status"].get("StateChangeReason", "")
            print(f"Query {state}: {reason}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)

    rows = []
    next_token = None
    while True:
        kwargs = {"QueryExecutionId": qid, "MaxResults": 100}
        if next_token:
            kwargs["NextToken"] = next_token
        results = client.get_query_results(**kwargs)
        result_set = results.get("ResultSet", {})
        row_list = result_set.get("Rows", [])
        rows.extend(row_list)
        next_token = results.get("NextToken")
        if not next_token:
            break

    if not rows:
        print("No rows returned.")
        return

    # First row is often header
    def cell(row, i):
        d = row.get("Data", [])
        if i < len(d):
            return (d[i].get("VarCharValue") or "").strip()
        return ""

    print("Columns in daylight_osm_features:")
    print("-" * 60)
    for row in rows:
        col_name = cell(row, 0)
        data_type = cell(row, 1)
        comment = cell(row, 2) if len(row.get("Data", [])) > 2 else ""
        if col_name and not col_name.startswith("#"):  # skip partition info header if any
            line = f"  {col_name:<20} {data_type}"
            if comment:
                line += f"  # {comment}"
            print(line)
    print("-" * 60)
    print(f"Total: {len([r for r in rows if cell(r, 0) and not cell(r, 0).startswith('#')])} columns")


if __name__ == "__main__":
    main()
