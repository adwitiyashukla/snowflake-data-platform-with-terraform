resource "snowflake_service_user" "deployer" {
  name              = "${var.database}_DEPLOYER"
  rsa_public_key    = var.deployer_public_key
  default_role      = snowflake_account_role.functional["DEPLOYER"].name
  default_warehouse = snowflake_warehouse.this["BUILD"].name
  default_namespace = snowflake_database.this.name
  comment           = "github actions"
}

resource "snowflake_service_user" "ops" {
  name              = "${var.database}_OPS"
  rsa_public_key    = var.ops_public_key
  default_role      = snowflake_account_role.functional["OPS"].name
  default_warehouse = snowflake_warehouse.this["QUERY"].name
  default_namespace = snowflake_database.this.name
  network_policy    = length(var.ops_allowed_ips) > 0 ? snowflake_network_policy.ops[0].name : null
  comment           = "pulse ops cli"
}

resource "snowflake_grant_account_role" "deployer_user" {
  role_name = snowflake_account_role.functional["DEPLOYER"].name
  user_name = snowflake_service_user.deployer.name
}

resource "snowflake_grant_account_role" "ops_user" {
  role_name = snowflake_account_role.functional["OPS"].name
  user_name = snowflake_service_user.ops.name
}
