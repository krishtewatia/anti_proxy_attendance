# MongoDB Atlas: a free (M0) cluster in Mumbai. Data is encrypted at rest and
# connections require TLS; both are always on for Atlas clusters.
#
# The database user is NOT created here: its password would be stored in the
# Terraform state. infra/scripts/secrets.py creates the user and writes the
# connection string straight to SSM Parameter Store.

resource "mongodbatlas_project" "main" {
  name   = var.atlas_project_name
  org_id = var.atlas_org_id
}

resource "mongodbatlas_advanced_cluster" "main" {
  project_id   = mongodbatlas_project.main.id
  name         = var.atlas_cluster_name
  cluster_type = "REPLICASET"

  replication_specs = [
    {
      region_configs = [
        {
          # M0 is the free tier: a shared ("TENANT") cluster hosted on AWS.
          provider_name         = "TENANT"
          backing_provider_name = "AWS"
          region_name           = "AP_SOUTH_1"
          priority              = 7
          electable_specs = {
            instance_size = "M0"
          }
        }
      ]
    }
  ]
}

# Only the instance's current public address may connect. The address changes
# when the instance is stopped and started, so infra/scripts/tf.py passes it in
# after each start. No address: nobody can connect.
resource "mongodbatlas_project_ip_access_list" "instance" {
  count      = var.atlas_allowed_ip == "" ? 0 : 1
  project_id = mongodbatlas_project.main.id
  ip_address = var.atlas_allowed_ip
  comment    = "${local.name} instance"
}
