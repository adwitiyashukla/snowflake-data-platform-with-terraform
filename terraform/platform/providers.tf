terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 2.20"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }

  backend "s3" {
    key          = "pulse/platform.tfstate"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}

provider "snowflake" {
  organization_name        = var.snowflake_organization
  account_name             = var.snowflake_account
  user                     = var.snowflake_user
  role                     = var.terraform_role
  authenticator            = "SNOWFLAKE_JWT"
  private_key              = var.snowflake_private_key_path == null ? null : file(var.snowflake_private_key_path)
  preview_features_enabled = ["snowflake_table_resource", "snowflake_pipe_resource"]
}

provider "snowflake" {
  alias                    = "accountadmin"
  organization_name        = var.snowflake_organization
  account_name             = var.snowflake_account
  user                     = var.snowflake_user
  role                     = "ACCOUNTADMIN"
  authenticator            = "SNOWFLAKE_JWT"
  private_key              = var.snowflake_private_key_path == null ? null : file(var.snowflake_private_key_path)
  preview_features_enabled = ["snowflake_table_resource", "snowflake_pipe_resource"]
}
