locals {
  schemas = {
    RAW          = "landing zone, one variant column per event as it arrived"
    MODEL        = "dynamic tables built from raw by the migrations"
    GOVERNANCE   = "tags, masking and row access policies, network rules"
    SCHEMACHANGE = "migration history"
  }
}

resource "snowflake_database" "this" {
  name                           = var.database
  comment                        = "product events platform"
  data_retention_time_in_days    = var.raw_retention_days
  drop_public_schema_on_creation = true
}

resource "snowflake_schema" "this" {
  for_each = local.schemas

  database = snowflake_database.this.name
  name     = each.key
  comment  = each.value
}
