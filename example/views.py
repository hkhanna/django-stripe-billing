from django.contrib.auth import get_user_model
from django.views.generic import RedirectView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from billing import models
from billing.mixins import BillingMixin

User = get_user_model()


class IndexView(RedirectView):
    pattern_name = "account_login"


class ProfileView(LoginRequiredMixin, BillingMixin, TemplateView):
    template_name = "example/profile.html"

    def get_context_data(self, **kwargs):
        # Create a paid plan for convenience in this example app.
        models.Plan.objects.get_or_create(
            type=models.Plan.Type.PAID_PUBLIC,
            defaults={"display_price": 9, "name": "Paid Plan", "price_id": "setme"},
        )
        return super().get_context_data(**kwargs)
