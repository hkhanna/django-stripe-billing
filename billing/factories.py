from django.contrib.auth import get_user_model
from django.utils import timezone
import factory
import factory.random
from factory.faker import faker

from . import models

factory.random.reseed_random(42)

User = get_user_model()
fake = faker.Faker()  # This is to use faker without the factory_boy wrapper


def set_customer_paying(customer):
    """Takes a customer and flips the switches to make it paying"""
    customer.customer_id = fake.pystr()
    customer.plan = PlanFactory(paid=True)
    customer.payment_state = models.Customer.PaymentState.OK
    customer.current_period_end = fake.date_time_this_month(
        before_now=False, after_now=True, tzinfo=timezone.utc
    )
    customer.subscription_id = fake.pystr()
    customer.save()


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

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override the default ``_create`` with our custom call."""
        manager = cls._get_manager(model_class)
        # The default would use ``manager.create(*args, **kwargs)``
        return manager.create_user(*args, **kwargs)

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
            set_customer_paying(obj.customer)

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
