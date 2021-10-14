import pytest
from django.urls import reverse
from django.utils import timezone

from .. import factories, models


@pytest.fixture
def user(upcoming_period_end):
    user = factories.UserFactory(
        paying=True,
        customer__subscription_id="sub",
        customer__current_period_end=upcoming_period_end,
    )
    assert "paid.paying" == user.customer.state  # Gut check
    return user


def test_cancel_subscription(client, customer):
    """Canceling a subscription sets payment_state to off,
    does not renew at the end of the billing period but otherwise
    does not affect the billing plan."""

    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {
            "object": {"id": "sub", "status": "active", "cancel_at_period_end": True}
        },
    }
    response = client.post(url, payload, content_type="application/json")
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OFF
    assert customer.current_period_end > timezone.now()
    assert customer.state == "paid.will_cancel"


def test_reactivate_subscription(client, customer):
    """Reactivating a subscription that will be canceled before the end of the billing cycle"""
    customer.payment_state = models.Customer.PaymentState.OFF
    customer.save()
    assert customer.state == "paid.will_cancel"

    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {
            "object": {"id": "sub", "status": "active", "cancel_at_period_end": False}
        },
    }
    response = client.post(url, payload, content_type="application/json")
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OK
    assert customer.current_period_end > timezone.now()
    assert customer.state == "paid.paying"
