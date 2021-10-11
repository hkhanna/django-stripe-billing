"""Stripe webhook functionality"""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.reverse import reverse

from .. import models, factories


@pytest.fixture
def user():
    return factories.UserFactory()


@pytest.fixture
def paid_plan():
    return factories.PlanFactory(paid=True)


@pytest.fixture
def upcoming_period_end():
    """Period that is upcoming for renewal"""
    return factories.fake.future_datetime(end_date="+5d", tzinfo=timezone.utc)


@pytest.fixture
def session(user, paid_plan, mock_stripe_checkout):
    session = mock_stripe_checkout.Session.retrieve.return_value
    current_period_end = timezone.now() + timedelta(days=30)
    cc_info = factories.cc_info()
    session.client_reference_id = user.id
    session.subscription.id = "sub_paid"
    session.subscription.status = "active"
    session.subscription.current_period_end = current_period_end.timestamp()
    session.subscription.default_payment_method.card = cc_info
    session.customer.id = factories.id("cus")
    session.line_items = {"data": [{"price": {"id": paid_plan.price_id}}]}
    return session


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
    url = reverse("billing:stripe_webhook")
    payload = {"id": "evt_test", "object": "event", "type": "test"}
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    assert 1 == models.StripeEvent.objects.count()


def test_bad_json(client):
    """Malformed JSON"""
    url = reverse("billing:stripe_webhook")
    payload = "bad json"
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 400
    assert models.StripeEvent.objects.count() == 0


def test_unrecognized_type(client):
    """Unrecognized event type"""
    url = reverse("billing:stripe_webhook")
    payload = {"id": "evt_test", "object": "event", "type": "bad.type"}
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert models.StripeEvent.Status.ERROR == models.StripeEvent.objects.first().status


def test_create_subscription(client, user, paid_plan, session, mock_stripe_checkout):
    """checkout.session.completed should set the customer_id, plan, current_period_end,
    payment_state and card_info"""
    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": factories.id("sess")}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock_stripe_checkout.Session.retrieve.call_count == 1

    user.refresh_from_db()
    assert paid_plan == user.customer.plan
    assert user.customer.customer_id == session.customer.id
    assert user.customer.payment_state == models.Customer.PaymentState.OK
    assert (
        session.subscription.current_period_end
        == user.customer.current_period_end.timestamp()
    )
    assert "sub_paid" == user.customer.subscription_id
    assert "paid.paying" == user.customer.state
    assert json.dumps(user.customer.cc_info, sort_keys=True) == json.dumps(
        session.subscription.default_payment_method.card,
        sort_keys=True,
    )
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )


def test_create_subscription_mismatched_customer_id(
    client, user, session, mock_stripe_checkout
):
    """A mismatched customer_id returned from the Session should log an error and update the User's customer_id."""
    url = reverse("billing:stripe_webhook")
    user.customer.customer_id = "cus_mismatch"
    user.customer.save()
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": factories.id("sess")}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock_stripe_checkout.Session.retrieve.call_count == 1
    user.refresh_from_db()
    assert user.customer.customer_id == session.customer.id
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )


def test_create_subscription_metadata(caplog, client, session, mock_stripe_customer):
    """Creation of a subscription updates the metadata on a Customer."""
    mock_stripe_customer.retrieve.return_value.metadata = {}
    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": factories.id("sess")}},
    }
    with caplog.at_level("ERROR"):
        response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock_stripe_customer.retrieve.call_count == 1
    assert mock_stripe_customer.modify.call_count == 1
    assert len(caplog.records) == 0
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )


def test_create_subscription_bad_metadata(
    caplog, client, session, mock_stripe_customer
):
    mock_stripe_customer.retrieve.return_value.metadata = {
        "user_pk": "bad",
        "application": "bad",
    }
    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": factories.id("sess")}},
    }
    with caplog.at_level("ERROR"):
        response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock_stripe_customer.retrieve.call_count == 1
    assert mock_stripe_customer.modify.call_count == 0
    assert len(caplog.records) == 2
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )


def test_renewed(client, customer):
    """A renewal was successfully processed for the next billing cycle"""
    # https://stripe.com/docs/billing/subscriptions/webhooks#tracking
    # Listen to an invoice webhook
    url = reverse("billing:stripe_webhook")
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
    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub", "status": "past_due"}},
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
    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub", "status": "canceled"}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    assert customer.current_period_end == upcoming_period_end
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OFF

    # Since the subscription doesn't expire for a couple days, it will be in a paid.canceled state.
    assert "paid.canceled" == customer.state

    # If the current_period_end is in the past, it should be in a free_default.canceled state.
    customer.current_period_end = factories.fake.past_datetime(
        "-1d", tzinfo=timezone.utc
    )
    customer.save()
    assert "free_default.canceled" == customer.state


def test_incomplete_expired(client, customer):
    """An initial payment failure not cured for 23 hours will cancel the subscription"""
    # Listen to customer.subscription.updated. status=incomplete_expired

    # The Customer has to be in the incomplete signup state.
    customer.current_period_end = None
    customer.payment_state = models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD
    customer.save()
    assert "free_default.incomplete.requires_payment_method" == customer.state

    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub", "status": "incomplete_expired"}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OFF
    assert "free_default.canceled.incomplete" == customer.state


def test_payment_method_automatically_updated(client, customer):
    """A network can update a user's credit card automatically"""
    # Listen to payment_method.automatically_updated.
    # See https://stripe.com/docs/saving-cards#automatic-card-updates
    url = reverse("billing:stripe_webhook")
    new_card = {"brand": "amex", "exp_month": 8, "exp_year": 2021, "last4": 1234}
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "payment_method.automatically_updated",
        "data": {"object": {"customer": customer.customer_id, "card": new_card}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
    customer.refresh_from_db()
    assert customer.payment_state == models.Customer.PaymentState.OK
    assert new_card == customer.cc_info
    assert "paid.paying" == customer.state
