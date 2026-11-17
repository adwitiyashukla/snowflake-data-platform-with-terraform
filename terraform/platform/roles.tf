locals {
  access_roles = {
    RAW_READ    = "read the landing zone"
    MODEL_READ  = "read the modeled tables"
    MODEL_WRITE = "create modeled tables, tags and policies"
  }

  functional_roles = {
    DEPLOYER   = "ci user, runs migrations and pr environments"
    ANALYST    = "reads every modeled table with pii masked"
    ANALYST_EU = "reads modeled rows for eu countries only"
    PII_READER = "sees personal data unmasked, held only by the deployer so refreshes store real values"
    OPS        = "reads usage, cost and load history"
  }

  role_grants = {
    DEPLOYER   = ["RAW_READ", "MODEL_READ", "MODEL_WRITE"]
    ANALYST    = ["MODEL_READ"]
    ANALYST_EU = ["MODEL_READ"]
    PII_READER = ["MODEL_READ"]
    OPS        = ["RAW_READ"]
  }

  role_pairs = {
    for pair in flatten([
      for functional, access_list in local.role_grants : [
        for access in access_list : {
          functional = functional
          access     = access
        }
      ]
    ]) : "${pair.functional}_${pair.access}" => pair
  }
}

resource "snowflake_account_role" "access" {
  for_each = local.access_roles

  name    = "${var.database}_${each.key}"
  comment = each.value
}

resource "snowflake_account_role" "functional" {
  for_each = local.functional_roles

  name    = "${var.database}_${each.key}"
  comment = each.value
}

resource "snowflake_grant_account_role" "access_to_functional" {
  for_each = local.role_pairs

  role_name        = snowflake_account_role.access[each.value.access].name
  parent_role_name = snowflake_account_role.functional[each.value.functional].name
}

resource "snowflake_grant_account_role" "pii_reader_to_deployer" {
  role_name        = snowflake_account_role.functional["PII_READER"].name
  parent_role_name = snowflake_account_role.functional["DEPLOYER"].name
}

resource "snowflake_grant_account_role" "functional_to_sysadmin" {
  for_each = local.functional_roles

  role_name        = snowflake_account_role.functional[each.key].name
  parent_role_name = "SYSADMIN"
}
