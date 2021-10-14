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
    customer.payment_state = models.Customer.PaymentState.OFF
    customer.plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
    customer.current_period_end = None
    customer.subscription_id = None
    customer.save()
    assert customer.state == "free_default.new"

    url = reverse("billing_checkout:create_portal_session")
    response = auth_client.post(url)
    assert mock_stripe_billing_portal.Session.create.call_count == 0
    assert response.status_code == 302
    assert response.url == settings.PORTAL_RETURN_URL


def test_cancel_subscription(client, customer, mock_stripe_subscription):
    """Cancelation lifecycle. From initial cancelation to Stripe cancel_at_period_end
    webhook to final subscription deletion webhook."""
    # Step 1 - Canceling a subscription and calls out to Stripe to cancel at period end."""

    # This is basically what Portal does if you cancel through it.
    customer.cancel_subscription(immediate=False)
    assert (
        customer.state == "paid.paying"
    )  # No change to state until we receive the webhook.
    assert mock_stripe_subscription.modify.called is True

    # Step 2 - Stripe sends cancel at period end webhook, resulting
    # in the correct Customer state."""

    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {
            "object": {"id": "sub", "status": "active", "cancel_at_period_end": True},
            "previous_attributes": {"cancel_at_period_end": False},
        },
    }
    client.post(url, payload, content_type="application/json")
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OFF
    assert customer.current_period_end > timezone.now()
    assert customer.state == "paid.will_cancel"

    # Step 3 - Stripe sends subscription deletion webhook once the
    # subscription is truly deleted, resulting in the correct Customer state.
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {"id": "sub", "status": "canceled", "cancel_at_period_end": False}
        },
    }
    client.post(url, payload, content_type="application/json")
    customer.refresh_from_db()
    assert customer.state == "free_default.new"


def test_cancel_subscription_immediately(client, customer, mock_stripe_subscription):
    """Immediately canceling a subscription calls out to Stripe to cancel immediately."""
    customer.cancel_subscription(immediate=True)
    assert mock_stripe_subscription.delete.called is True
    assert (
        customer.state == "paid.paying"
    )  # No change to state until we receive the webhook.

    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {"id": "sub", "status": "canceled", "cancel_at_period_end": False}
        },
    }
    client.post(url, payload, content_type="application/json")
    customer.refresh_from_db()
    assert customer.state == "free_default.new"


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
            "object": {"id": "sub", "status": "active", "cancel_at_period_end": False},
            "previous_attributes": {"cancel_at_period_end": True},
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
