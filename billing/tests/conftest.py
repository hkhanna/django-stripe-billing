import pytest
import stripe
from unittest.mock import Mock
from django.utils import timezone
from datetime import timedelta

from .. import factories


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass


@pytest.fixture(autouse=True)
def mock_stripe_customer(monkeypatch):
    """Fixture to monkeypatch the stripe.Customer.* methods"""
    mock = Mock()
    monkeypatch.setattr(stripe, "Customer", mock)
    return mock


@pytest.fixture(autouse=True)
def mock_stripe_payment_method(monkeypatch):
    """Fixture to monkeypatch the stripe.PaymentMethod.* methods"""
    mock = Mock()
    monkeypatch.setattr(stripe, "PaymentMethod", mock)
    return mock


@pytest.fixture(autouse=True)
def mock_stripe_subscription(monkeypatch):
    """Fixture to monkeypatch the stripe.Subscription.* methods"""
    mock = Mock()
    monkeypatch.setattr(stripe, "Subscription", mock)
    return mock


@pytest.fixture(autouse=True)
def mock_stripe_checkout(monkeypatch):
    """Fixture to monkeypatch stripe.checkout.* methods"""
    mock = Mock()
    mock.Session.create.return_value.url = "https://example.net/stripe_checkout/"
    monkeypatch.setattr(stripe, "checkout", mock)
    return mock


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
def user():
    return factories.UserFactory()


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def paid_plan():
    return factories.PlanFactory(paid=True)
