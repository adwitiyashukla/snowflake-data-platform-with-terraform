locals {
  warehouses = {
    LOAD  = "copy runs by hand and backfills, snowpipe brings its own compute"
    BUILD = "dynamic table refreshes, migrations and pr environments"
    QUERY = "analysts and the ops cli"
  }
}

resource "snowflake_resource_monitor" "this" {
  provider = snowflake.accountadmin
  for_each = local.warehouses

  name                      = "${var.database}_${each.key}_MON"
  credit_quota              = var.daily_credit_quota[each.key]
  frequency                 = "DAILY"
  start_timestamp           = "IMMEDIATELY"
  notify_triggers           = [80]
  suspend_trigger           = 100
  suspend_immediate_trigger = 120
}

resource "snowflake_warehouse" "this" {
  provider = snowflake.accountadmin
  for_each = local.warehouses

  name                         = "${var.database}_${each.key}_WH"
  warehouse_size               = var.warehouse_size
  auto_suspend                 = var.auto_suspend_seconds
  auto_resume                  = true
  initially_suspended          = true
  resource_monitor             = snowflake_resource_monitor.this[each.key].fully_qualified_name
  statement_timeout_in_seconds = 1800
  comment                      = each.value
}
