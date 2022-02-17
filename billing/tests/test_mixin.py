import pytest
from pytest_django.asserts import assertTemplateUsed
from django.urls import reverse
from ..models import Customer


@pytest.mark.parametrize(
    "state",
    [
        "free_default.new",
        "free_private.expired",
        "free_default.past_due.requires_payment_method",
        "paid.past_due.requires_payment_method",
        "paid.paying",
        "paid.will_cancel",
        "free_default.canceled.missed_webhook",
        "free_private.indefinite",
        "free_private.will_expire",
    ],
)
def test_billing_mixin(auth_client, monkeypatch, state):
    """BillingMixin should not raise no matter what the Customer state"""
    monkeypatch.setattr(Customer, "state", state)
    url = reverse("profile")
    response = auth_client.get(url)
    assertTemplateUsed(response, "profile.html")
