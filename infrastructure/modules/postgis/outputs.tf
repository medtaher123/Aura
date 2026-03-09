output "enabled" {
  description = "Whether PostGIS module is enabled"
  value       = var.enabled
}

output "endpoint" {
  description = "PostGIS endpoint"
  value       = try(aws_db_instance.this[0].address, null)
}

output "port" {
  description = "PostGIS port"
  value       = try(aws_db_instance.this[0].port, null)
}

output "database_name" {
  description = "PostGIS database name"
  value       = var.db_name
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN for auto-managed master password"
  value       = try(aws_db_instance.this[0].master_user_secret[0].secret_arn, null)
}

output "security_group_id" {
  description = "Security group attached to PostGIS instance"
  value       = try(aws_security_group.this[0].id, null)
}

