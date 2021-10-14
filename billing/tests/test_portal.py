import pytest
from django.urls import reverse
from django.utils import timezone

from .. import factories, models, settings


@pytest.fixture
def user(upcoming_period_end):
    user = factories.UserFactory(
        paying=True,
        customer__subscription_id="sub",
        customer__current_period_end=upcoming_period_end,
    )
    assert "paid.paying" == user.customer.state  # Gut check
    return user


def test_portal_happy(auth_client, mock_stripe_billing_portal):
    """A Customer can create a Stripe Portal session"""
    url = reverse("billing_checkout:create_portal_session")
    response = auth_client.post(url)
    assert mock_stripe_billing_portal.Session.create.call_count == 1
    assert response.status_code == 302
    assert response.url == mock_stripe_billing_portal.Session.create.return_value.url


def test_portal_wrong_state(auth_client, customer, mock_stripe_billing_portal):
    """A Customer with an inapproprate state should not be able to access the Stripe Portal"""
    customer.cancel_subscription(immediate=True, notify_stripe=False)
    assert customer.state == "free_default.new"

    url = reverse("billing_checkout:create_portal_session")
    response = auth_client.post(url)
    assert mock_stripe_billing_portal.Session.create.call_count == 0
    assert response.status_code == 302
    assert response.url == settings.PORTAL_RETURN_URL


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
    customer.cancel_subscription(immediate=False, notify_stripe=True)
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
