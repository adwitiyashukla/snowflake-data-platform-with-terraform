data "aws_caller_identity" "current" {}

locals {
  bucket_name      = "${var.bucket_prefix}-${data.aws_caller_identity.current.account_id}"
  events_location  = "s3://${local.bucket_name}/${var.events_prefix}"
  loader_role_name = "${lower(var.database)}-snowflake-loader"
  loader_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.loader_role_name}"
}

resource "aws_s3_bucket" "events" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "events" {
  bucket                  = aws_s3_bucket.events.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "events" {
  bucket = aws_s3_bucket.events.id

  rule {
    id     = "expire-loaded-events"
    status = "Enabled"

    filter {
      prefix = var.events_prefix
    }

    expiration {
      days = var.event_file_expiry_days
    }
  }
}

resource "snowflake_storage_integration_aws" "events" {
  name                      = "${var.database}_S3"
  enabled                   = true
  storage_provider          = "S3"
  storage_allowed_locations = [local.events_location]
  storage_aws_role_arn      = local.loader_role_arn
  comment                   = "lets snowflake assume the loader role in our aws account"
}

data "aws_iam_policy_document" "loader_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [snowflake_storage_integration_aws.events.describe_output[0].iam_user_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [snowflake_storage_integration_aws.events.describe_output[0].external_id]
    }
  }
}

data "aws_iam_policy_document" "loader_access" {
  statement {
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.events.arn}/${var.events_prefix}*"]
  }

  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.events.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.events_prefix}*"]
    }
  }
}

resource "aws_iam_role" "loader" {
  name               = local.loader_role_name
  assume_role_policy = data.aws_iam_policy_document.loader_trust.json
}

resource "aws_iam_role_policy" "loader" {
  name   = "read-events"
  role   = aws_iam_role.loader.id
  policy = data.aws_iam_policy_document.loader_access.json
}

resource "time_sleep" "loader_role" {
  depends_on      = [aws_iam_role_policy.loader]
  create_duration = "20s"
}

resource "snowflake_stage_external_s3" "events" {
  name                = "EVENTS_STAGE"
  database            = snowflake_database.this.name
  schema              = snowflake_schema.this["RAW"].name
  url                 = local.events_location
  storage_integration = snowflake_storage_integration_aws.events.name
  comment             = "gzipped ndjson written by the producer"

  file_format {
    json {
      compression       = "AUTO"
      strip_null_values = "false"
    }
  }
}

resource "snowflake_table" "events" {
  database                    = snowflake_database.this.name
  schema                      = snowflake_schema.this["RAW"].name
  name                        = "EVENTS"
  comment                     = "landing table, one row per event as loaded by snowpipe"
  change_tracking             = true
  data_retention_time_in_days = var.raw_retention_days

  column {
    name     = "RECORD"
    type     = "VARIANT"
    nullable = false
  }

  column {
    name = "FILE_NAME"
    type = "VARCHAR"
  }

  column {
    name = "FILE_ROW_NUMBER"
    type = "NUMBER(38,0)"
  }

  column {
    name = "LOADED_AT"
    type = "TIMESTAMP_NTZ(9)"

    default {
      expression = "CURRENT_TIMESTAMP()"
    }
  }
}

resource "snowflake_pipe" "events" {
  database    = snowflake_database.this.name
  schema      = snowflake_schema.this["RAW"].name
  name        = "EVENTS_PIPE"
  auto_ingest = true
  comment     = "loads every new object under the events prefix"

  copy_statement = join(" ", [
    "copy into ${snowflake_table.events.fully_qualified_name} (RECORD, FILE_NAME, FILE_ROW_NUMBER)",
    "from (select $1, metadata$filename, metadata$file_row_number",
    "from @${snowflake_stage_external_s3.events.fully_qualified_name})",
    "on_error = continue",
  ])

  depends_on = [time_sleep.loader_role]
}

resource "aws_s3_bucket_notification" "events" {
  bucket = aws_s3_bucket.events.id

  queue {
    queue_arn     = snowflake_pipe.events.show_output[0].notification_channel
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = var.events_prefix
  }
}
