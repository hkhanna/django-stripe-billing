from . import models


class BillingMixin:
    @staticmethod
    def state_note(customer):
        """Convenience to avoid doing lots of logic in the template"""
        if customer.state == "free_default.new":
            return ""
        elif customer.state == "free_default.canceled.missed_webhook":
            return "There is an issue with your subscription. Please contact support."
        elif customer.state == "paid.paying":
            return f"Subscription renews on {customer.current_period_end}."
        elif customer.state == "paid.will_cancel":
            return f"Subscription cancelled. Access available until {customer.current_period_end}."
        elif customer.state == "free_private.indefinite":
            return f"Staff plan, no expiration."
        elif customer.state == "free_private.will_expire":
            return f"Staff plan expires on {customer.current_period_end}."
        elif customer.state == "free_private.expired":
            return f"Subscription expired on {customer.current_period_end}"
        elif customer.state in (
            "free_default.past_due.requires_payment_method",
            "paid.past_due.requires_payment_method",
        ):
            return "There is a problem with your credit card. Please provide a new one or try again."
        else:
            return "There is an issue with your subscription. Please contact support."

    def get_context_data(self, **kwargs):
        ctx = {"billing_enabled": True}
        customer = self.request.user.customer
        state = customer.state

        if state in (
            "free_default.new",
            "free_private.expired",
        ):
            ctx["url"] = "billing:create_checkout_session"
            paid_plan = models.Plan.objects.filter(
                type=models.Plan.Type.PAID_PUBLIC
            ).first()
            # Don't use this Mixin if you have not created a Paid plan.
            if not paid_plan:
                return {"billing_enabled": False}
            ctx["paid_plan_id"] = paid_plan.id
            ctx["button_text"] = "Upgrade to Paid Plan"
        elif state in (
            "free_default.past_due.requires_payment_method",
            "paid.past_due.requires_payment_method",
            "paid.paying",
        ):
            ctx["url"] = "billing:create_portal_session"
            ctx["button_text"] = "Update or Cancel Plan"
        elif state == "paid.will_cancel":
            ctx["url"] = "billing:create_portal_session"
            ctx["button_text"] = "Reactivate Paid Plan"
        elif state == "free_default.canceled.missed_webhook":
            ctx["url"] = "profile"
            ctx["button_text"] = "There is a problem with your subscription."
        ctx["state_note"] = self.state_note(customer)
        ctx["current_plan"] = customer.plan
        return ctx
