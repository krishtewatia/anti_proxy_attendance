# Deployments from GitHub Actions, without any stored AWS key.
#
# The workflow proves who it is with a short-lived token from GitHub (OIDC).
# AWS accepts it only for this repository's main branch, and the role it gets
# can do one thing: run the deploy document below on this one instance.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# The only command the pipeline can run on the instance: switch to a release.
# The release must be a full commit id; anything else is refused before it
# reaches a shell.
resource "aws_ssm_document" "deploy" {
  name            = "${local.name}-deploy"
  document_type   = "Command"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Switch the instance to the images of one commit and wait until the site is healthy"
    parameters = {
      ReleaseSha = {
        type           = "String"
        description    = "Full commit id whose images are in the registry"
        allowedPattern = "^[0-9a-f]{40}$"
      }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deploy"
      inputs = {
        timeoutSeconds = "900"
        runCommand     = ["/opt/antiproxy/deploy.sh {{ ReleaseSha }}"]
      }
    }]
  })
}

resource "aws_iam_role" "deploy" {
  name = "${local.name}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # Workflows running on main of this repository, and nothing else:
          # not pull requests, not other branches, not forks.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy" {
  name = "run-the-deploy-document"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RunTheDeployDocumentOnTheInstance"
        Effect = "Allow"
        Action = "ssm:SendCommand"
        Resource = [
          aws_ssm_document.deploy.arn,
          aws_instance.app.arn,
        ]
      },
      {
        Sid      = "ReadTheResult"
        Effect   = "Allow"
        Action   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
        Resource = "*"
      },
      {
        Sid      = "SeeWhetherTheInstanceIsRunning"
        Effect   = "Allow"
        Action   = "ec2:DescribeInstances"
        Resource = "*"
      },
    ]
  })
}

output "deploy_role_arn" {
  description = "Role GitHub Actions assumes to deploy (repository variable AWS_DEPLOY_ROLE_ARN)."
  value       = aws_iam_role.deploy.arn
}

output "deploy_document" {
  value = aws_ssm_document.deploy.name
}
