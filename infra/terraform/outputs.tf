output "site_url" {
  value = "https://${var.site_host}"
}

output "instance_id" {
  value = aws_instance.app.id
}

output "instance_public_ip" {
  description = "Empty while the instance is stopped."
  value       = aws_instance.app.public_ip
}

output "instance_state" {
  value = aws_ec2_instance_state.app.state
}

output "run_mode" {
  value = var.run_mode
}

output "aws_region" {
  value = var.aws_region
}

output "ssm_path" {
  description = "Parameter Store path the instance reads its secrets from."
  value       = local.ssm_path
}

output "atlas_project_id" {
  value = mongodbatlas_project.main.id
}

output "atlas_cluster_name" {
  value = mongodbatlas_advanced_cluster.main.name
}

output "atlas_srv_address" {
  description = "mongodb+srv:// address of the cluster, without credentials."
  value       = mongodbatlas_advanced_cluster.main.connection_strings.standard_srv
}
