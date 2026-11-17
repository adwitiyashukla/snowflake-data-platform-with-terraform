import json

from pulse.snow import rows


def percentile(values, share):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def table(records, columns):
    if not records:
        return "(no rows)"
    widths = {col: len(col) for col in columns}
    cells = []
    for row in records:
        line = {}
        for col in columns:
            value = row.get(col)
            if isinstance(value, float):
                text = f"{value:.4f}" if abs(value) < 100 else f"{value:.1f}"
            else:
                text = "" if value is None else str(value)
            line[col] = text
            widths[col] = max(widths[col], len(text))
        cells.append(line)
    header = "  ".join(col.ljust(widths[col]) for col in columns)
    body = ["  ".join(line[col].ljust(widths[col]) for col in columns) for line in cells]
    return "\n".join([header, "-" * len(header), *body])


def list_objects(s3, bucket, prefix):
    found = {}
    token = None
    while True:
        args = {"Bucket": bucket, "Prefix": prefix}
        if token:
            args["ContinuationToken"] = token
        page = s3.list_objects_v2(**args)
        for item in page.get("Contents", []):
            found[item["Key"]] = item["LastModified"]
        if not page.get("IsTruncated"):
            return found
        token = page.get("NextContinuationToken")


def latency(conn, config, s3, bucket, hours):
    sf = config.snowflake
    full_table = f"{sf.database}.{sf.raw_schema}.{sf.raw_table}"
    loads = rows(
        conn,
        f"select file_name, pipe_received_time, last_load_time, row_count, error_count, status "
        f"from table({sf.database}.information_schema.copy_history("
        f"table_name => '{full_table}', "
        f"start_time => dateadd(hour, -{int(hours)}, current_timestamp())))",
    )
    objects = list_objects(s3, bucket, config.aws.events_prefix)
    seconds = []
    matched = 0
    for load in loads:
        name = load["file_name"] or ""
        modified = objects.get(config.aws.events_prefix + name)
        if modified is None:
            modified = next((ts for key, ts in objects.items() if key.endswith(name)), None)
        if modified is None or load["last_load_time"] is None:
            continue
        matched += 1
        seconds.append((load["last_load_time"] - modified).total_seconds())
    status = rows(
        conn, f"select system$pipe_status('{sf.database}.{sf.raw_schema}.{sf.pipe}') as s"
    )
    pipe = json.loads(status[0]["s"]) if status else {}
    return {
        "hours": hours,
        "files_in_s3": len(objects),
        "files_loaded": sum(1 for load in loads if load["status"] == "Loaded"),
        "files_failed": sum(
            1 for load in loads if load["status"] not in ("Loaded", "Load in progress")
        ),
        "rows_loaded": sum(load["row_count"] or 0 for load in loads),
        "rows_with_errors": sum(load["error_count"] or 0 for load in loads),
        "files_matched": matched,
        "latency_p50_s": percentile(seconds, 0.5),
        "latency_p95_s": percentile(seconds, 0.95),
        "latency_max_s": max(seconds) if seconds else None,
        "pipe_state": pipe.get("executionState"),
        "pipe_pending_files": pipe.get("pendingFileCount"),
    }


def credits(conn, config, days):
    sf = config.snowflake
    window = (
        f"date_range_start => dateadd(day, -{int(days)}, current_timestamp()), "
        f"date_range_end => current_timestamp()"
    )
    warehouses = rows(
        conn,
        f"select warehouse_name, sum(credits_used) as credits, "
        f"sum(credits_used_compute) as compute, sum(credits_used_cloud_services) as cloud "
        f"from table({sf.database}.information_schema.warehouse_metering_history({window})) "
        f"group by 1 order by 1",
    )
    pipes = rows(
        conn,
        f"select pipe_name, sum(credits_used) as credits, sum(bytes_inserted) as bytes, "
        f"sum(files_inserted) as files "
        f"from table({sf.database}.information_schema.pipe_usage_history({window}, "
        f"pipe_name => '{sf.database}.{sf.raw_schema}.{sf.pipe}')) group by 1",
    )
    events = rows(conn, f"select count(*) as n from {sf.database}.{sf.raw_schema}.{sf.raw_table}")[
        0
    ]["n"]
    prefix = sf.database.upper() + "_"
    pipe_credits = sum(float(row["credits"] or 0) for row in pipes)
    wh_credits = {
        row["warehouse_name"]: float(row["credits"] or 0)
        for row in warehouses
        if row["warehouse_name"].startswith(prefix)
    }
    total = pipe_credits + sum(wh_credits.values())
    per_million = total / events * 1e6 if events else None
    return {
        "days": days,
        "events_loaded": events,
        "pipe_credits": round(pipe_credits, 4),
        "warehouse_credits": {k: round(v, 4) for k, v in wh_credits.items()},
        "total_credits": round(total, 4),
        "credits_per_million_events": round(per_million, 4) if per_million is not None else None,
        "usd_per_million_events": (
            round(per_million * sf.credit_price_usd, 2) if per_million is not None else None
        ),
        "pipe_files": sum(int(row["files"] or 0) for row in pipes),
        "pipe_bytes": sum(int(row["bytes"] or 0) for row in pipes),
    }


def warehouses(conn, config, days):
    sf = config.snowflake
    prefix = sf.database.upper() + "_"
    listed = [row for row in rows(conn, "show warehouses") if row["name"].startswith(prefix)]
    window = (
        f"date_range_start => dateadd(day, -{int(days)}, current_timestamp()), "
        f"date_range_end => current_timestamp()"
    )
    metering = {
        row["warehouse_name"]: float(row["credits"] or 0)
        for row in rows(
            conn,
            f"select warehouse_name, sum(credits_used) as credits "
            f"from table({sf.database}.information_schema.warehouse_metering_history({window})) "
            f"group by 1",
        )
    }
    load = {
        row["warehouse_name"]: row
        for row in rows(
            conn,
            f"select warehouse_name, avg(avg_running) as running, avg(avg_queued_load) as queued "
            f"from table({sf.database}.information_schema.warehouse_load_history({window})) "
            f"group by 1",
        )
    }
    hours = min(int(days) * 24, 167)
    activity = {}
    for wh in listed:
        stats = rows(
            conn,
            f"select count(*) as queries, avg(total_elapsed_time) as avg_ms, "
            f"avg(queued_overload_time) as queued_ms, sum(bytes_scanned) as scanned "
            f"from table({sf.database}.information_schema.query_history_by_warehouse("
            f"warehouse_name => '{wh['name']}', "
            f"end_time_range_start => dateadd(hour, -{hours}, current_timestamp()), "
            f"result_limit => 10000)) where execution_status = 'SUCCESS'",
        )
        activity[wh["name"]] = stats[0] if stats else {}
    report = []
    for wh in listed:
        name = wh["name"]
        auto_suspend = int(wh["auto_suspend"] or 0)
        used = metering.get(name, 0.0)
        queued = float((load.get(name) or {}).get("queued") or 0)
        running = float((load.get(name) or {}).get("running") or 0)
        stats = activity.get(name) or {}
        verdicts = []
        if auto_suspend == 0 or auto_suspend > config.ops.idle_auto_suspend_seconds:
            verdicts.append("auto_suspend too long")
        if queued > config.ops.queued_load_threshold:
            verdicts.append("queueing, size up or add clusters")
        if used == 0:
            verdicts.append("unused in window")
        report.append(
            {
                "warehouse": name,
                "size": wh["size"],
                "auto_suspend": auto_suspend,
                "credits": round(used, 4),
                "avg_running": round(running, 3),
                "avg_queued": round(queued, 3),
                "queries": int(stats.get("queries") or 0),
                "avg_ms": round(float(stats.get("avg_ms") or 0)),
                "queued_ms": round(float(stats.get("queued_ms") or 0)),
                "gb_scanned": round(int(stats.get("scanned") or 0) / 1e9, 2),
                "verdict": ", ".join(verdicts) or "fine",
            }
        )
    return report


def tables(conn, config):
    sf = config.snowflake
    listed = rows(conn, f"show dynamic tables in schema {sf.database}.{sf.model_schema}")
    history = rows(
        conn,
        f"select name, state, refresh_action, refresh_trigger, "
        f"timestampdiff(second, refresh_start_time, refresh_end_time) as seconds, "
        f"statistics:numInsertedRows::number as inserted, "
        f"statistics:numDeletedRows::number as deleted "
        f"from table({sf.database}.information_schema.dynamic_table_refresh_history("
        f"name_prefix => '{sf.database}.{sf.model_schema}.')) "
        f"where refresh_start_time >= dateadd(day, -1, current_timestamp()) "
        f"order by refresh_start_time desc",
    )
    by_name = {}
    for row in history:
        by_name.setdefault(row["name"], []).append(row)
    report = []
    for dt in listed:
        runs = by_name.get(dt["name"], [])
        durations = [float(run["seconds"]) for run in runs if run["seconds"] is not None]
        report.append(
            {
                "table": dt["name"],
                "state": dt["scheduling_state"],
                "target_lag": dt["target_lag"],
                "refresh_mode": dt["refresh_mode"],
                "refreshes_24h": len(runs),
                "incremental": sum(1 for run in runs if run["refresh_action"] != "FULL"),
                "avg_seconds": round(sum(durations) / len(durations), 1) if durations else None,
                "rows_inserted_24h": sum(int(run["inserted"] or 0) for run in runs),
                "rows_deleted_24h": sum(int(run["deleted"] or 0) for run in runs),
            }
        )
    return report
