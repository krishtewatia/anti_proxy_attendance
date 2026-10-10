# on_demand mode only: stop the instance every night, so an instance that was
# left running does not use up credits. In always_on mode none of this exists.

resource "aws_iam_role" "auto_stop" {
  count = var.run_mode == "on_demand" ? 1 : 0
  name  = "${local.name}-auto-stop"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "auto_stop" {
  count = var.run_mode == "on_demand" ? 1 : 0
  name  = "stop-the-instance"
  role  = aws_iam_role.auto_stop[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ec2:StopInstances"
      Resource = aws_instance.app.arn
    }]
  })
}

resource "aws_scheduler_schedule" "auto_stop" {
  count       = var.run_mode == "on_demand" ? 1 : 0
  name        = "${local.name}-auto-stop"
  description = "Stops the instance every night while run_mode is on_demand"

  schedule_expression          = var.auto_stop_schedule
  schedule_expression_timezone = var.auto_stop_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
    role_arn = aws_iam_role.auto_stop[0].arn
    input    = jsonencode({ InstanceIds = [aws_instance.app.id] })
  }
}
