resource "snowflake_network_rule" "ops" {
  count = length(var.ops_allowed_ips) > 0 ? 1 : 0

  name       = "OPS_ALLOWLIST"
  database   = snowflake_database.this.name
  schema     = snowflake_schema.this["GOVERNANCE"].name
  type       = "IPV4"
  mode       = "INGRESS"
  value_list = var.ops_allowed_ips
  comment    = "where the ops cli is allowed to connect from"
}

resource "snowflake_network_policy" "ops" {
  count = length(var.ops_allowed_ips) > 0 ? 1 : 0

  name                      = "${var.database}_OPS_POLICY"
  allowed_network_rule_list = [snowflake_network_rule.ops[0].fully_qualified_name]
  comment                   = "pins the ops service user to known addresses"
}
