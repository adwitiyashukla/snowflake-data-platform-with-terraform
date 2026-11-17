output "events_bucket" {
  value = aws_s3_bucket.events.bucket
}

output "events_location" {
  value = local.events_location
}

output "loader_role_arn" {
  value = aws_iam_role.loader.arn
}

output "snowflake_iam_user_arn" {
  value = snowflake_storage_integration_aws.events.describe_output[0].iam_user_arn
}

output "pipe_notification_channel" {
  value = snowflake_pipe.events.show_output[0].notification_channel
}

output "warehouses" {
  value = { for key, wh in snowflake_warehouse.this : key => wh.name }
}

output "service_users" {
  value = {
    deployer = snowflake_service_user.deployer.name
    ops      = snowflake_service_user.ops.name
  }
}
