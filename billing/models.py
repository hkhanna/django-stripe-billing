import logging
from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify

from . import services

logger = logging.getLogger(__name__)


class Limit(models.Model):
    """The specific attributes associated with a Plan"""

    name = models.CharField(max_length=254, unique=True)
    default = models.IntegerField(
        help_text="If a Plan hasn't set this limit, the Plan will use this default value."
    )

    def __str__(self):
        return self.name


class Plan(models.Model):
    """The various billing and permissioning plans offered"""

    name = models.CharField(max_length=254, unique=True)
    limits = models.ManyToManyField(Limit, related_name="plans", through="PlanLimit")
    created_at = models.DateTimeField(auto_now_add=True)
    display_price = models.PositiveIntegerField(
        help_text="Price displayed to users for plan"
    )
    price_id = models.CharField(
        null=True,
        blank=True,
        unique=True,
        max_length=254,
        verbose_name="Stripe Price ID.",
        help_text="Paid plans must set this and it may only be set if the Plan's type is paid.",
    )

    class Type(models.TextChoices):
        FREE_DEFAULT = "free_default", "Free (Default)"
        FREE_PRIVATE = "free_private", "Free (Private)"  # Staff plans
        PAID_PUBLIC = "paid_public", "Paid (Public)"
        PAID_PRIVATE = "paid_private", "Paid (Private)"  # Grandfathered or custom plans

    type = models.CharField(
        max_length=254,
        help_text="The type of plan",
        choices=Type.choices,
        default=Type.FREE_DEFAULT,
    )

    def clean(self):
        # This is in a clean method because this is only configured via the admin.
        if self.price_id and self.type not in (
            Plan.Type.PAID_PUBLIC,
            Plan.Type.PAID_PRIVATE,
        ):
            raise ValidationError({"type": "Plans with a price_id must be paid."})
        if (
            self.type in (Plan.Type.PAID_PUBLIC, Plan.Type.PAID_PRIVATE)
            and not self.price_id
        ):
            raise ValidationError({"price_id": "Paid plans must have a price_id."})
        if (
            self.type == Plan.Type.FREE_DEFAULT
            and Plan.objects.filter(type=Plan.Type.FREE_DEFAULT)
            .exclude(id=self.id)
            .exists()
        ):
            raise ValidationError(
                {"type": "There already exists a Default (Free) plan."}
            )
        if (
            self.type == Plan.Type.PAID_PUBLIC
            and Plan.objects.filter(type=Plan.Type.PAID_PUBLIC)
            .exclude(id=self.id)
            .exists()
        ):
            raise ValidationError(
                {
                    "type": "There already exists a Paid (Public) plan. Multiple public paid plans not available yet."
                }
            )

    @property
    def slug(self):
        return slugify(self.name)

    def __str__(self):
        return self.name

    class Meta:
        constraints = [
            # There can only be 1 default free plan. This is enforced here and in the clean method.
            # We do it in both places so that the admin will return a friendly error but also if
            # there's a screwup somewhere in the code outside the admin, it will IntegrityError
            # rather than corrupting the database.
            UniqueConstraint(
                fields=["type"],
                condition=Q(type="free_default"),
                name="max_1_free_default_plan",
            )
        ]


class PlanLimit(models.Model):
    plan = models.ForeignKey("Plan", on_delete=models.CASCADE)
    limit = models.ForeignKey("Limit", on_delete=models.CASCADE)
    value = models.IntegerField()

    class Meta:
        constraints = [
            UniqueConstraint(fields=["plan", "limit"], name="unique_plan_limit")
        ]

    def __str__(self):
        return self.limit.name


class Customer(models.Model):
    """User attributes related to billing and payment"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    customer_id = models.CharField(
        max_length=254,
        unique=True,
        null=True,
        blank=True,
        verbose_name="Stripe Customer ID",
    )
    plan = models.ForeignKey("Plan", on_delete=models.PROTECT)
    current_period_end = models.DateTimeField(null=True, blank=True)

    def cancel_subscription(self, immediate):
        if not immediate and self.payment_state == "off":
            logger.error(
                f"User.id={self.user.id} does not have an active subscription to cancel."
            )
            return False

        logger.info(
            f"User.id={self.user.id} canceling subscription_id {self.subscription_id}"
        )
        self.save()
        return services.stripe_cancel_subscription(self.subscription_id, immediate)

    @property
    def subscription(self):
        """Get the Customer's StripeSubscription, if any, dealing with the situation of
        multiple subscriptions, which can happen erroneously or after a cancelation and renewal."""
        # We prefer an active subscription to a past_due subscription to every other subscription.
        # If there are still multiple subscriptions after that heuristic, we take the most recently created one.
        subscriptions = self.stripesubscription_set.order_by("-created").all()
        for s in subscriptions:
            if s.status == "active":
                return s

        for s in subscriptions:
            if s.status == "past_due":
                return s

        if len(subscriptions) > 0:
            return subscriptions[0]

        # TODO: test no subscriptions returns no subscription or subscription_id

    # TODO: Refactor these properties into more sensible things (after tests pass)
    @property
    def subscription_id(self):
        if self.subscription:
            return self.subscription.id

    @property
    def payment_state(self):
        if not self.subscription:
            return "off"
        if self.subscription.status == StripeSubscription.Status.ACTIVE:
            return "ok"
        if self.subscription.status == StripeSubscription.Status.PAST_DUE:
            return "requires_payment_method"
        return "off"

    @property
    def state(self):
        if (
            self.plan.type == Plan.Type.FREE_DEFAULT
            and self.payment_state == "off"
            and self.current_period_end is None
            and self.subscription_id is None
        ):
            return "free_default.new"

        if (
            self.plan.type != Plan.Type.FREE_DEFAULT
            and self.payment_state == "off"
            and self.current_period_end is not None
            and self.current_period_end < timezone.now()
            and self.subscription_id is not None
        ):
            # There's a paid or free private plan, but it's expired, and there's no more payments coming.
            # This will only happen if we miss the final cancelation webhook or reactivation webhook.
            # This will present as a canceled subscription.
            return "free_default.canceled.missed_webhook"

        if (
            self.plan.type in (Plan.Type.PAID_PUBLIC, Plan.Type.PAID_PRIVATE)
            and self.current_period_end is not None
            and self.current_period_end > timezone.now()
            and self.payment_state == "ok"
            and self.subscription_id is not None
        ):
            # There's a paid plan, it's not expired, and there's payments coming.
            return "paid.paying"

        if (
            self.plan.type in (Plan.Type.PAID_PUBLIC, Plan.Type.PAID_PRIVATE)
            and self.current_period_end is not None
            and self.current_period_end > timezone.now()
            and self.payment_state == "off"
            and self.subscription_id is not None
        ):
            # There's a paid plan, it's not expired, but there's no more payments coming.
            # This Customer can be reactivated.
            return "paid.will_cancel"

        if (
            self.plan.type == Plan.Type.FREE_PRIVATE
            and self.current_period_end is None
            and self.payment_state == "off"
            and self.subscription_id is None
        ):
            # Free private plan with no expiration date
            return "free_private.indefinite"

        if (
            self.plan.type == Plan.Type.FREE_PRIVATE
            and self.current_period_end is not None
            and self.current_period_end > timezone.now()
            and self.payment_state == "off"
            and self.subscription_id is None
        ):
            # Free private plan with an expiration date in the future.
            # An expiration date in the past yields free_private.expired.
            return "free_private.will_expire"

        if (
            self.plan.type == Plan.Type.FREE_PRIVATE
            and self.current_period_end is not None
            and self.current_period_end < timezone.now()
            and self.payment_state == "off"
            and self.subscription_id is None
        ):
            # Free private plan with an expiration date in the past.
            return "free_private.expired"

        if (
            self.plan.type in (Plan.Type.PAID_PUBLIC, Plan.Type.PAID_PRIVATE)
            and self.payment_state == "requires_payment_method"
            and self.current_period_end is not None
            and self.current_period_end < timezone.now()
            and self.subscription_id is not None
        ):
            # There's a plan, but payment is required. The current_period_end is set in the past, which
            # means that Stripe is still retrying payment and its a past_due situation, but the application
            # is going to treat the subscription as expired since current_period_end has lapsed.
            return "free_default.past_due.requires_payment_method"

        if (
            self.plan.type in (Plan.Type.PAID_PUBLIC, Plan.Type.PAID_PRIVATE)
            and self.payment_state == "requires_payment_method"
            and self.current_period_end is not None
            and self.current_period_end >= timezone.now()
            and self.subscription_id is not None
        ):
            # There's a plan, but payment is required. The current_period_end is set in the future, which
            # means that Stripe is still retrying payment, and it is a past_due situation, but the paid plan
            # still has some time left, so the user can continue to use it until Stripe succeeds.
            return "paid.past_due.requires_payment_method"

        logger.error(f"Customer.id={self.id} cannot properly calculate status.")
        return "invalid"

    def clean(self):
        # Admin can't save the Customer if the state would be 'invalid'
        if self.state == "invalid":
            raise ValidationError(
                "This would make the Customer state invalid. Please fix and try again."
            )

    def get_limit(self, name):
        plan = self.plan

        plan_expired = (
            self.current_period_end is not None
            and self.current_period_end < timezone.now()
        )
        if plan_expired:
            # If the Plan is expired, use the values from the free_default plan
            plan = Plan.objects.get(type=Plan.Type.FREE_DEFAULT)
        elif self.current_period_end is None and self.plan.type in (
            Plan.Type.PAID_PUBLIC,
            Plan.Type.PAID_PRIVATE,
        ):
            # If current_period_end is None, use the values from the free_default plan if the user's plan is paid.
            # I.e., paid plans with no current_period_end are incomplete and use the free_default limits
            # and free_private plans without current_period_end exist indefinitely.
            plan = Plan.objects.get(type=Plan.Type.FREE_DEFAULT)

        limit = plan.planlimit_set.filter(limit__name=name).first()
        if limit:
            return limit.value
        else:
            limit = Limit.objects.get(name=name)
            return limit.default

    def __str__(self):
        return f"{self.user}"


class StripeSubscription(models.Model):
    """Models a Stripe Subscription, hewing closely to the Stripe data model."""

    id = models.CharField(max_length=254, primary_key=True)
    customer = models.ForeignKey(Customer, null=True, on_delete=models.SET_NULL)
    # TODO: think about hard delete user
    current_period_end = models.DateTimeField()
    price_id = models.CharField(max_length=254)
    cancel_at_period_end = models.BooleanField(default=False)
    created = models.DateTimeField()

    class Status(models.TextChoices):
        INCOMPLETE = "incomplete"
        INCOMPLETE_EXPIRED = "incomplete_expired"
        ACTIVE = "active"
        PAST_DUE = "past_due"
        CANCELED = "canceled"
        # TRIALING = "trialing" -- not used
        # UNPAID = "unpaid" -- not used

    status = models.CharField(max_length=254, choices=Status.choices)

    def sync_to_customer(self):
        """Synchronizes data on the StripeSubscription instance to the Customer instance,
        if and as appropriate."""

        # Sync the plan and end date if the subscription is active.
        if self.status == StripeSubscription.Status.ACTIVE:
            plan = Plan.objects.get(price_id=self.price_id)
            self.customer.plan = plan
            self.customer.current_period_end = self.current_period_end

        # If the subscription is finally deleted, downgrade the customer to free_default and
        # zero-out the current_period_end. (TODO test)
        if self.status == StripeSubscription.Status.CANCELED:
            plan = Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
            self.customer.plan = plan
            self.customer.current_period_end = None

        self.customer.save()


class StripeEvent(models.Model):
    """Stripe Events from webhooks"""

    event_id = models.CharField(max_length=254)
    payload_type = models.CharField(max_length=254)
    received_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    # body can't be a JSONField since Stripe webhook signature checking will fail
    body = models.TextField()
    headers = models.JSONField()
    note = models.TextField(blank=True)

    class Status(models.TextChoices):
        NEW = "new"
        PENDING = "pending"
        PROCESSED = "processed"
        IGNORED = "ignored"
        ERROR = "error"

    status = models.CharField(
        max_length=127, choices=Status.choices, default=Status.NEW
    )

    def __str__(self):
        return self.event_id
