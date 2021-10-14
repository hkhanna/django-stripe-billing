"""Stripe lifecycle webhook functionality. Webhooks where the user has taken
some action in Checkout or Portal are found elsewhere."""

from datetime import timedelta
from freezegun import freeze_time

import pytest
from django.utils import timezone
from django.urls import reverse

from .. import models, factories


@pytest.fixture
def customer(upcoming_period_end):
    """Customer that is coming up for renewal"""
    user = factories.UserFactory(
        paying=True,
        customer__subscription_id="sub",
        customer__current_period_end=upcoming_period_end,
    )
    assert "paid.paying" == user.customer.state  # Gut check
    return user.customer


def test_create_event(client):
    """Create event"""
    url = reverse("billing_api:stripe_webhook")
    payload = {"id": "evt_test", "object": "event", "type": "test"}
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    assert 1 == models.StripeEvent.objects.count()


def test_bad_json(client):
    """Malformed JSON"""
    url = reverse("billing_api:stripe_webhook")
    payload = "bad json"
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 400
    assert models.StripeEvent.objects.count() == 0


def test_unrecognized_type(client):
    """Unrecognized event type"""
    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "bad.type",
        "data": {"object": None},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.IGNORED == models.StripeEvent.objects.first().status
    )


def test_renewed(client, customer):
    """A renewal was successfully processed for the next billing cycle"""
    # https://stripe.com/docs/billing/subscriptions/webhooks#tracking
    # Listen to an invoice webhook
    url = reverse("billing_api:stripe_webhook")
    mock_period_end = timezone.now() + timedelta(days=30)
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "invoice.paid",
        "data": {
            "object": {
                # See https://stackoverflow.com/questions/22601521/stripe-webhook-events-renewal-of-subscription
                # for why we need the billing_reason.
                "billing_reason": "subscription_cycle",
                "subscription": "sub",
                "lines": {"data": [{"period": {"end": mock_period_end.timestamp()}}]},
            }
        },
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    customer.refresh_from_db()
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    assert customer.current_period_end == mock_period_end
    assert "paid.paying" == customer.state


def test_payment_failure(client, customer, upcoming_period_end):
    """A renewal payment failed"""
    # https://stripe.com/docs/billing/subscriptions/webhooks#payment-failures
    # https://stripe.com/docs/billing/subscriptions/overview#build-your-own-handling-for-recurring-charge-failures
    # Listen to customer.subscription.updated. status=past_due
    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "invoice.payment_failed",
        "data": {
            "object": {"subscription": "sub", "billing_reason": "subscription_cycle"}
        },
    }

    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    assert customer.current_period_end == upcoming_period_end
    customer.refresh_from_db()
    assert (
        customer.payment_state == models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD
    )
    assert "paid.past_due.requires_payment_method" == customer.state


def test_payment_failure_permanent(client, customer, upcoming_period_end):
    """Renewal payment has permanently failed"""
    # Listen to customer.subscription.updated. status=canceled
    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {"id": "sub", "status": "canceled", "cancel_at_period_end": False}
        },
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    assert customer.current_period_end == upcoming_period_end
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OFF
    assert "free_default.new" == customer.state


def test_incomplete_expired(client, customer):
    """An initial payment failure not cured for 23 hours will cancel the subscription"""
    # Listen to customer.subscription.updated. status=incomplete_expired

    # The Customer has to be in the incomplete signup state.
    customer.current_period_end = None
    customer.payment_state = models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD
    customer.save()
    assert "free_default.incomplete.requires_payment_method" == customer.state

    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub",
                "status": "incomplete_expired",
                "cancel_at_period_end": False,
            }
        },
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OFF
    assert "free_default.new" == customer.state


def test_cancel_miss_final_cancel(client, customer):
    """User cancels and then we miss the final Stripe subscription cancelation
    webhook or the reactivation webhook."""
    # N.B. Missing the initial cancelation webhook is nbd since the Portal
    # will remain accessible and eventually final cancelation will come through.
    customer.payment_state = models.Customer.PaymentState.OFF
    customer.save()
    assert "paid.will_cancel" == customer.state

    sixty_days_hence = timezone.now() + timedelta(days=60)
    with freeze_time(sixty_days_hence):
        customer.refresh_from_db()
        assert "free_default.canceled.missed_webhook" == customer.state


def test_past_due_miss_final_cancel(client, customer):
    """User is past_due and then we miss the invoice.paid webhook or
    final Stripe cancelation webhook"""
    # This is not ideal. A missed webhook here will leave the user totally unable to subscribe.
    # N.B. We can't test for the situation where a user is incomplete and then we miss the incomplete_expired webhook.
    # It wouldn't be good. The user will be unable to subscribe.
    customer.payment_state = models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD
    customer.save()
    assert "paid.past_due.requires_payment_method" == customer.state
    sixty_days_hence = timezone.now() + timedelta(days=60)
    with freeze_time(sixty_days_hence):
        customer.refresh_from_db()
        assert "free_default.past_due.requires_payment_method" == customer.state


def test_link_event_to_user(client, customer):
    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {"id": "sub", "status": "canceled", "cancel_at_period_end": False}
        },
    }
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    event = models.StripeEvent.objects.first()
    assert event.user == customer.user
