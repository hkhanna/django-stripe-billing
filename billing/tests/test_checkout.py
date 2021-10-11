import pytest
from django.urls import reverse

from .. import factories, settings, models


@pytest.fixture
def user():
    return factories.UserFactory()


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def paid_plan():
    return factories.PlanFactory(paid=True)


def test_create_checkout_session_happy(auth_client, paid_plan, mock_stripe_checkout):
    """create_checkout_session creates a Stripe Session
    and redirects to the appropriate URL"""
    url = reverse("checkout:create_checkout_session")
    payload = {"plan_id": paid_plan.id}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.call_count == 1
    assert response.status_code == 302
    assert response.url == mock_stripe_checkout.Session.create.return_value.url


def test_create_checkout_session_bad_plan_id(
    auth_client, paid_plan, mock_stripe_checkout
):
    """Bad plan id should cancel the checkout flow"""
    url = reverse("checkout:create_checkout_session")
    payload = {"plan_id": paid_plan.id + 1}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_create_checkout_session_bad_plan_id(
    auth_client, paid_plan, mock_stripe_checkout
):
    """No plan id should cancel the checkout flow"""
    url = reverse("checkout:create_checkout_session")
    payload = {}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_create_checkout_session_already_paid(
    auth_client, paid_plan, user, mock_stripe_checkout
):
    """A User with an existing subscription may not access the create_checkout_session endpoint."""
    factories.set_customer_paying(user.customer)
    url = reverse("checkout:create_checkout_session")
    payload = {"plan_id": paid_plan.id}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_nonpublic_plan(auth_client, mock_stripe_checkout):
    """Billing Plans that are not public cannot be accessed via Checkout"""
    plan = factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE)
    url = reverse("checkout:create_checkout_session")
    payload = {"plan_id": plan.id}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
