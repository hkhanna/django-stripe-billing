import pytest
import stripe
from unittest.mock import Mock
from django.utils import timezone

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


@pytest.fixture(autouse=True)
def mock_stripe_billing_portal(monkeypatch):
    """Fixture to monkeypatch stripe.billing_portal.* methods"""
    mock = Mock()
    mock.Session.create.return_value.url = "https://example.net/stripe_billing_portal/"
    monkeypatch.setattr(stripe, "billing_portal", mock)
    return mock


@pytest.fixture
def user():
    return factories.UserFactory()


@pytest.fixture
def customer(user):
    return user.customer


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def paid_plan():
    return factories.PlanFactory(paid=True)


@pytest.fixture
def upcoming_period_end():
    """Period that is upcoming for renewal"""
    return factories.fake.future_datetime(end_date="+5d", tzinfo=timezone.utc)
