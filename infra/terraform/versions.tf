terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 2.0"
    }
  }

  # State is kept on the machine that runs Terraform and is ignored by git.
  # It holds no secret: secrets are written to SSM Parameter Store by
  # infra/scripts/secrets.py and never pass through Terraform.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Credentials come from the environment (MONGODB_ATLAS_PUBLIC_API_KEY and
# MONGODB_ATLAS_PRIVATE_API_KEY), never from a file in this repository.
provider "mongodbatlas" {}
