# Instance health alarms, inside the free tier (10 alarms, 1,000 emails a month).
#
# * The host behind the instance fails (StatusCheckFailed_System): AWS moves
#   the instance to healthy hardware by itself (auto-recover) and emails.
# * The instance itself stops answering (StatusCheckFailed_Instance): email,
#   so someone can look at `python infra/scripts/tf.py logs`.
#
# Emails go to alert_email, the same address as the budget alerts. AWS sends a
# confirmation email first; the alarms email nobody until it is confirmed.
# A stopped instance reports nothing, so the nightly stop raises no alarm.

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "host_failed" {
  alarm_name          = "${local.name}-host-failed"
  alarm_description   = "The hardware behind the instance failed; AWS recovers the instance onto healthy hardware."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = aws_instance.app.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = ["arn:aws:automate:${var.aws_region}:ec2:recover", aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "instance_failed" {
  alarm_name          = "${local.name}-instance-failed"
  alarm_description   = "The instance stopped answering its status check. Look at `python infra/scripts/tf.py logs`."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  dimensions          = { InstanceId = aws_instance.app.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
