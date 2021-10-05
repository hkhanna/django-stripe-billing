"""Tests for the limitations of various billing plans."""
# In this billing app, we can test generically that Limits are resolved properly based on the active plan.
# It may be sensible to do additional testing in other apps for specific, real Limits, e.g., the maximum
# number of emails a user can send.
import pytest
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from .. import factories, models


@pytest.fixture
def paid_plan():
    factories.PlanLimitFactory(
        plan__paid=True,
        value=1,
        limit__name="Limit 1",
        limit__default=99,
    )
    factories.PlanLimitFactory(
        plan__paid=True,
        value=2,
        limit__name="Limit 2",
        limit__default=98,
    )
    factories.LimitFactory(name="Limit 3", default=97)


@pytest.fixture
def customer(paid_plan):
    user = factories.UserFactory(paying=True)
    return user.customer


@pytest.mark.django_db
def test_get_limit(customer):
    """Customer.get_limit returns the PlanLimit value."""
    value = customer.get_limit("Limit 1")
    assert value == 1
    value = customer.get_limit("Limit 2")
    assert value == 2


@pytest.mark.django_db
def test_get_limit_default(customer):
    """Customer.get_limit returns the Limit default if the Plan does not have have that PlanLimit."""
    value = customer.get_limit("Limit 3")
    assert value == 97


@pytest.mark.django_db
def test_get_limit_nonexist(customer):
    """Attempting to get a non-existent limit will raise."""
    with pytest.raises(ObjectDoesNotExist):
        customer.get_limit("Bad Limit")


@pytest.mark.django_db
def test_get_limit_expired_plan(customer):
    """Getting a limit for an expired paid plan should return the limit from the free_default plan."""
    # Expire the plan
    customer.current_period_end = timezone.now() - timedelta(minutes=1)
    customer.save()

    free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
    factories.PlanLimitFactory(
        plan=free_default_plan, value=50, limit__name="Limit 1"
    )  # Will get existing Limit
    value = customer.get_limit("Limit 1")
    assert value == 50

    # Because the free_default plan does not have Limit 2, it should use the default.
    value = customer.get_limit("Limit 2")
    assert value == 98


@pytest.mark.django_db
def test_get_limit_paid_plan_with_no_date(customer):
    """A paid plan with no current_period_end should be treated as expired."""
    customer.current_period_end = None
    customer.save()
    free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
    factories.PlanLimitFactory(
        plan=free_default_plan, value=50, limit__name="Limit 1"
    )  # Will get existing Limit
    value = customer.get_limit("Limit 1")
    assert value == 50


@pytest.mark.django_db
def test_get_limit_free_private_plan_expired(paid_plan):
    """A free_private plan with an expired current_period_end should return the limits from the free_default plan."""
    plan = factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE)
    user = factories.UserFactory(
        paying=False,
        customer__plan=plan,
        customer__current_period_end=timezone.now() - timedelta(days=10),
    )
    factories.PlanLimitFactory(
        plan=plan, value=0, limit__name="Limit 1"
    )  # Will get existing Limit

    free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
    factories.PlanLimitFactory(
        plan=free_default_plan, value=50, limit__name="Limit 1"
    )  # Will get existing Limit
    value = user.customer.get_limit("Limit 1")
    assert value == 50

    # Because the free_default plan does not have Limit 2, it should use the default.
    value = user.customer.get_limit("Limit 2")
    assert value == 98


@pytest.mark.django_db
def test_get_limit_free_private_plan_with_no_date(paid_plan):
    """A free_private plan with no current_period_end should NOT be treated as expired."""
    plan = factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE)
    user = factories.UserFactory(
        paying=False, customer__plan=plan, customer__current_period_end=None
    )
    factories.PlanLimitFactory(
        plan=plan, value=0, limit__name="Limit 1"
    )  # Will get existing Limit

    # These defaults won't be used.
    free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
    factories.PlanLimitFactory(plan=free_default_plan, value=50, limit__name="Limit 1")

    value = user.customer.get_limit("Limit 1")
    assert value == 0
