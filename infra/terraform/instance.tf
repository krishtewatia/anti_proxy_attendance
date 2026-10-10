locals {
  name     = "${var.project}-${var.environment}"
  ssm_path = "/${var.project}/${var.environment}"

  # Pinned Docker Compose plugin (checked against this checksum on the instance).
  compose_version = "v5.6.0"
  compose_sha256  = "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a"

  # Pinned MongoDB database tools (mongodump for the nightly backup), checked
  # against the checksum MongoDB publishes for this archive.
  mongo_tools_version = "100.19.1"
  mongo_tools_sha256  = "0cdd6fe932291be6f4fa9eb0d148c392bf529e085151d677522378aebb03bcd3"

  # Settings the instance needs that are not secret. Secrets are never here:
  # the instance reads them from SSM Parameter Store when it starts.
  config_env = join("\n", [
    "AWS_REGION=${var.aws_region}",
    "SSM_PATH=${local.ssm_path}",
    "GITHUB_REPOSITORY=${var.github_repository}",
    "SITE_ADDRESS=${var.site_host}",
    "DUCKDNS_SUBDOMAIN=${split(".", var.site_host)[0]}",
    "IMAGE_PREFIX=${var.image_prefix}",
    "LIVENESS_MODE=${var.liveness_mode}",
    "ACME_CA=${var.acme_ca}",
    "SWAP_MB=${var.swap_mb}",
    "COMPOSE_VERSION=${local.compose_version}",
    "COMPOSE_SHA256=${local.compose_sha256}",
    "MONGO_TOOLS_VERSION=${local.mongo_tools_version}",
    "MONGO_TOOLS_SHA256=${local.mongo_tools_sha256}",
    "BACKUP_BUCKET=${aws_s3_bucket.backups.bucket}",
    "",
  ])

  scripts = {
    "start.sh"     = "0750"
    "deploy.sh"    = "0750"
    "bootstrap.sh" = "0750"
    "backup.sh"    = "0750"
    "load_env.py"  = "0640"
    "duckdns.py"   = "0640"
  }

  user_data = join("\n", [
    "#cloud-config",
    yamlencode({
      write_files = concat(
        [
          {
            path        = "/opt/antiproxy/config.env"
            permissions = "0644"
            content     = local.config_env
          },
          {
            path        = "/opt/antiproxy/release"
            permissions = "0644"
            content     = "${var.release_sha}\n"
          },
          {
            path        = "/etc/systemd/system/antiproxy.service"
            permissions = "0644"
            content     = replace(file("${path.module}/files/antiproxy.service"), "\r\n", "\n")
          },
          {
            path        = "/etc/systemd/system/antiproxy-backup.service"
            permissions = "0644"
            content     = replace(file("${path.module}/files/antiproxy-backup.service"), "\r\n", "\n")
          },
          {
            path        = "/etc/systemd/system/antiproxy-backup.timer"
            permissions = "0644"
            content     = replace(file("${path.module}/files/antiproxy-backup.timer"), "\r\n", "\n")
          },
        ],
        [
          for name, mode in local.scripts : {
            path        = "/opt/antiproxy/${name}"
            permissions = mode
            # A Windows checkout may hold these with CRLF line endings, which
            # would break them on the instance.
            content = replace(file("${path.module}/files/${name}"), "\r\n", "\n")
          }
        ],
      )
      runcmd = [["/opt/antiproxy/bootstrap.sh"]]
    }),
  ])
}

# Amazon Linux 2023, the current image published by AWS.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_caller_identity" "current" {}

# ------------------------------------------------------------------------------
# What the instance may do: be managed by Systems Manager, and read its own
# parameters. Nothing else.
# ------------------------------------------------------------------------------

resource "aws_iam_role" "instance" {
  name = "${local.name}-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "instance_ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "instance_parameters" {
  name = "read-own-parameters"
  role = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadDeploymentParameters"
        Effect   = "Allow"
        Action   = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_path}/*"
      },
      {
        # SecureString parameters are encrypted with the account's default
        # SSM key; decrypting is allowed only through Parameter Store.
        Sid      = "DecryptThroughParameterStore"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com" }
        }
      },
    ]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name}-instance"
  role = aws_iam_role.instance.name
}

# ------------------------------------------------------------------------------
# The instance
# ------------------------------------------------------------------------------

# This instance is the web server. With no load balancer and no NAT gateway
# (both cost money), a public address is how visitors reach Caddy and how the
# instance reaches the registry and the database. Only ports 80 and 443 are
# open (network.tf), so the scanner's "no public address" rule does not apply.
# nosemgrep: terraform.aws.security.aws-ec2-has-public-ip.aws-ec2-has-public-ip
resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name
  # No Elastic IP: the address is released whenever the instance stops, so a
  # stopped instance costs nothing but its volume.
  associate_public_ip_address = true

  # Compressed: the limit is 16 KB and the scripts come close to it. cloud-init
  # unpacks it by itself.
  user_data_base64 = base64gzip(local.user_data)
  # Changing a script here must not destroy the instance and its volume.
  user_data_replace_on_change = false

  # Standard mode: when CPU credits run out the instance slows down. The
  # default ("unlimited") would bill extra for sustained CPU use.
  credit_specification {
    cpu_credits = "standard"
  }

  # IMDSv2 only, and not reachable from inside the containers.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true

    tags = { Name = "${local.name}-root" }
  }

  tags = { Name = local.name }

  lifecycle {
    # A newer Amazon Linux image must not replace the running instance.
    ignore_changes = [ami, user_data, user_data_base64]
  }
}

resource "aws_ec2_instance_state" "app" {
  instance_id = aws_instance.app.id
  state       = var.instance_state
}
