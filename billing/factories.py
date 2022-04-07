from django.contrib.auth import get_user_model
from django.utils import timezone
import factory
import factory.random
from factory.faker import faker

from . import models

factory.random.reseed_random(42)

User = get_user_model()
fake = faker.Faker()  # This is to use faker without the factory_boy wrapper


class LimitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Limit
        django_get_or_create = ("name",)

    name = factory.Faker("numerify", text="Limit ####")
    default = factory.Faker("pyint", max_value=100)


class PlanFactory(factory.django.DjangoModelFactory):
    """Creates free_default Plan by default. Accepts trait paid."""

    class Meta:
        model = models.Plan
        # This is so we don't create >1 free_default plan. Downside is that we'll only ever have 1 plan
        # of each type if we use this factory.
        django_get_or_create = ("type",)

    name = factory.Faker("numerify", text="Plan ###")
    display_price = 0
    type = models.Plan.Type.FREE_DEFAULT

    class Params:
        paid = factory.Trait(
            type=models.Plan.Type.PAID_PUBLIC,
            display_price=factory.Faker("pyint", min_value=1, max_value=100),
            price_id=f"price_{fake.pystr()}",
        )


class PlanLimitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.PlanLimit

    plan = factory.SubFactory(PlanFactory)
    limit = factory.SubFactory(LimitFactory)
    value = factory.Faker("pyint", max_value=100)


class StripeSubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.StripeSubscription

    id = factory.Faker("pystr")
    customer = None  # This needs to be set.
    current_period_end = factory.Faker(
        "date_time_this_month", before_now=False, after_now=True, tzinfo=timezone.utc
    )
    price_id = factory.LazyFunction(lambda: PlanFactory(paid=True).price_id)
    cancel_at_period_end = False
    created = factory.LazyFunction(timezone.now)
    status = models.StripeSubscription.Status.ACTIVE

    @factory.post_generation
    def sync_to_customer(obj, *args, **kwargs):
        obj.sync_to_customer()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    username = factory.LazyAttribute(lambda obj: f"{obj.first_name}_{obj.last_name}")
    email = factory.LazyAttribute(
        lambda obj: f"{obj.first_name}.{obj.last_name}@example.com".lower()
    )
    password = "goodpass"

    # customer is always created by the signal and there isn't any way to prevent that.
    # These are a couple post-generation hooks allowing us to manipulate customer after its been created.
    # This is a poor man's "trait" since we can't use traits directly on the customer model because its
    # created by a signal and not by factory_boy.
    @factory.post_generation
    def paying(obj, create, extracted, **kwargs):
        if (
            not create
        ):  # This is the factoryboy "strategy": build vs create. This is incompatible with build.
            return

        if extracted:
            StripeSubscriptionFactory(customer=obj.customer)

    # If we pass in deep attributes to customer, this sets them properly.
    # Since it's defined after `paying`, it will overwrite that trait.
    @factory.post_generation
    def customer(obj, create, extracted, **kwargs):
        if (
            not create
        ):  # This is the factoryboy "strategy": build vs create. This is incompatible with build.
            return
        for k, v in kwargs.items():
            setattr(obj.customer, k, v)
        obj.customer.save()


def id(prefix):
    """Return a concatenation of the prefix and a random string"""
    return f"{prefix}_{fake.pystr()}"
