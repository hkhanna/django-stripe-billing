from django.contrib.auth import get_user_model
from django.views.generic import RedirectView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from billing import models

User = get_user_model()


class IndexView(RedirectView):
    pattern_name = "account_login"


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "example/profile.html"

    @staticmethod
    def state_note(customer):
        """Convenience to avoid doing lots of logic in the template"""
        # Maybe delete the Subscription immediately rather than at the end of the period.
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
        ctx = super().get_context_data(**kwargs)
        customer = self.request.user.customer
        state = customer.state

        if state in (
            "free_default.new",
            "free_private.expired",
        ):
            ctx["url"] = "billing:create_checkout_session"
            plan, _ = models.Plan.objects.get_or_create(
                type=models.Plan.Type.PAID_PUBLIC,
                defaults={"display_price": 9, "name": "Paid Plan", "price_id": "setme"},
            )
            ctx["plan_id"] = plan.id
            ctx["button_text"] = "Create Subscription"
        elif state in (
            "free_default.past_due.requires_payment_method",
            "paid.past_due.requires_payment_method",
            "paid.paying",
        ):
            ctx["url"] = "billing:create_portal_session"
            ctx["button_text"] = "Update or Cancel Subscription"
        elif state == "paid.will_cancel":
            ctx["url"] = "billing:create_portal_session"
            ctx["button_text"] = "Reactivate Subscription"
        elif state == "free_default.canceled.missed_webhook":
            ctx["url"] = "profile"
            ctx["button_text"] = "There is a problem with your subscription."
        ctx["state_note"] = self.state_note(customer)
        ctx[
            "current_plan"
        ] = f"{customer.plan.name} (${customer.plan.display_price}/mo)"
        return ctx
