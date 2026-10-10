# Spending alarms, by email.
#
# On a Free plan account nothing can be charged: usage is paid from credits
# and the account closes when they run out. So the alarm that matters is the
# first one, which watches how much of the credits has been used.

# 1. Credit use: usage at list price, before credits are applied.
resource "aws_budgets_budget" "credit_use" {
  name         = "${local.name}-credit-use"
  budget_type  = "COST"
  limit_amount = tostring(var.credit_budget_usd)
  limit_unit   = "USD"
  time_unit    = "ANNUALLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = var.credit_alert_thresholds_usd
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# 2. Real money: what would be charged after credits. Should stay at zero.
resource "aws_budgets_budget" "actual_spend" {
  name         = "${local.name}-actual-spend"
  budget_type  = "COST"
  limit_amount = "1"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 1
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 1
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
