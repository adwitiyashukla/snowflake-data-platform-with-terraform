locals {
  raw_schema        = snowflake_schema.this["RAW"].fully_qualified_name
  model_schema      = snowflake_schema.this["MODEL"].fully_qualified_name
  governance_schema = snowflake_schema.this["GOVERNANCE"].fully_qualified_name
  history_schema    = snowflake_schema.this["SCHEMACHANGE"].fully_qualified_name

  model_object_types = toset(["TABLES", "VIEWS", "DYNAMIC TABLES"])
  query_roles        = toset(["ANALYST", "ANALYST_EU", "PII_READER", "OPS"])
}

resource "snowflake_grant_privileges_to_account_role" "database_usage" {
  for_each = local.access_roles

  privileges        = each.key == "MODEL_WRITE" ? ["USAGE", "CREATE SCHEMA"] : ["USAGE"]
  account_role_name = snowflake_account_role.access[each.key].name

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.this.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "raw_read_schema" {
  privileges        = ["USAGE"]
  account_role_name = snowflake_account_role.access["RAW_READ"].name

  on_schema {
    schema_name = local.raw_schema
  }
}

resource "snowflake_grant_privileges_to_account_role" "raw_read_tables" {
  privileges        = ["SELECT"]
  account_role_name = snowflake_account_role.access["RAW_READ"].name

  on_schema_object {
    all {
      object_type_plural = "TABLES"
      in_schema          = local.raw_schema
    }
  }

  depends_on = [snowflake_table.events]
}

resource "snowflake_grant_privileges_to_account_role" "raw_read_future_tables" {
  privileges        = ["SELECT"]
  account_role_name = snowflake_account_role.access["RAW_READ"].name

  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = local.raw_schema
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "model_read_schema" {
  privileges        = ["USAGE"]
  account_role_name = snowflake_account_role.access["MODEL_READ"].name

  on_schema {
    schema_name = local.model_schema
  }
}

resource "snowflake_grant_privileges_to_account_role" "model_read_objects" {
  for_each = local.model_object_types

  privileges        = ["SELECT"]
  account_role_name = snowflake_account_role.access["MODEL_READ"].name

  on_schema_object {
    all {
      object_type_plural = each.key
      in_schema          = local.model_schema
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "model_read_future_objects" {
  for_each = local.model_object_types

  privileges        = ["SELECT"]
  account_role_name = snowflake_account_role.access["MODEL_READ"].name

  on_schema_object {
    future {
      object_type_plural = each.key
      in_schema          = local.model_schema
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "model_write_model_schema" {
  privileges        = ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE DYNAMIC TABLE"]
  account_role_name = snowflake_account_role.access["MODEL_WRITE"].name

  on_schema {
    schema_name = local.model_schema
  }
}

resource "snowflake_grant_privileges_to_account_role" "model_write_governance_schema" {
  privileges = [
    "USAGE",
    "CREATE TABLE",
    "CREATE TAG",
    "CREATE MASKING POLICY",
    "CREATE ROW ACCESS POLICY",
  ]
  account_role_name = snowflake_account_role.access["MODEL_WRITE"].name

  on_schema {
    schema_name = local.governance_schema
  }
}

resource "snowflake_grant_privileges_to_account_role" "model_write_history_schema" {
  privileges        = ["USAGE", "CREATE TABLE"]
  account_role_name = snowflake_account_role.access["MODEL_WRITE"].name

  on_schema {
    schema_name = local.history_schema
  }
}

resource "snowflake_grant_privileges_to_account_role" "model_write_account" {
  privileges        = ["APPLY MASKING POLICY", "APPLY ROW ACCESS POLICY", "APPLY TAG"]
  account_role_name = snowflake_account_role.access["MODEL_WRITE"].name
  on_account        = true
}

resource "snowflake_grant_privileges_to_account_role" "deployer_account" {
  privileges        = ["CREATE DATABASE"]
  account_role_name = snowflake_account_role.functional["DEPLOYER"].name
  on_account        = true
}

resource "snowflake_grant_privileges_to_account_role" "deployer_warehouse" {
  privileges        = ["USAGE"]
  account_role_name = snowflake_account_role.functional["DEPLOYER"].name

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.this["BUILD"].name
  }
}

resource "snowflake_grant_privileges_to_account_role" "query_warehouse" {
  for_each = local.query_roles

  privileges        = ["USAGE"]
  account_role_name = snowflake_account_role.functional[each.key].name

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.this["QUERY"].name
  }
}

resource "snowflake_grant_privileges_to_account_role" "ops_account" {
  privileges        = ["MONITOR USAGE"]
  account_role_name = snowflake_account_role.functional["OPS"].name
  on_account        = true
}

resource "snowflake_grant_privileges_to_account_role" "ops_warehouses" {
  for_each = local.warehouses

  privileges        = ["MONITOR"]
  account_role_name = snowflake_account_role.functional["OPS"].name

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.this[each.key].name
  }
}

resource "snowflake_grant_privileges_to_account_role" "ops_pipe" {
  privileges        = ["MONITOR"]
  account_role_name = snowflake_account_role.functional["OPS"].name

  on_schema_object {
    object_type = "PIPE"
    object_name = snowflake_pipe.events.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "ops_model_schema" {
  privileges        = ["USAGE"]
  account_role_name = snowflake_account_role.functional["OPS"].name

  on_schema {
    schema_name = local.model_schema
  }
}

resource "snowflake_grant_privileges_to_account_role" "ops_dynamic_tables" {
  privileges        = ["MONITOR"]
  account_role_name = snowflake_account_role.functional["OPS"].name

  on_schema_object {
    all {
      object_type_plural = "DYNAMIC TABLES"
      in_schema          = local.model_schema
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "ops_future_dynamic_tables" {
  privileges        = ["MONITOR"]
  account_role_name = snowflake_account_role.functional["OPS"].name

  on_schema_object {
    future {
      object_type_plural = "DYNAMIC TABLES"
      in_schema          = local.model_schema
    }
  }
}

resource "snowflake_grant_database_role" "ops_account_usage" {
  provider = snowflake.accountadmin
  for_each = toset(["USAGE_VIEWER", "OBJECT_VIEWER"])

  database_role_name = "\"SNOWFLAKE\".\"${each.key}\""
  parent_role_name   = snowflake_account_role.functional["OPS"].name
}
