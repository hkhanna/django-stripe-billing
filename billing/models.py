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
    subscription_id = models.CharField(
        max_length=254,
        unique=True,
        null=True,
        blank=True,
        verbose_name="Stripe Subscription ID",
    )

    class PaymentState(models.TextChoices):
        OFF = "off"
        OK = "ok"
        ERROR = "error"
        REQUIRES_PAYMENT_METHOD = "requires_payment_method"
        REQUIRES_ACTION = "requires_action"

    payment_state = models.CharField(
        max_length=128, default=PaymentState.OFF, choices=PaymentState.choices
    )

    def cancel_subscription(self, immediate):
        if not immediate and self.payment_state == Customer.PaymentState.OFF:
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
    def state(self):
        if (
            self.plan.type == Plan.Type.FREE_DEFAULT
            and self.payment_state == Customer.PaymentState.OFF
            and self.current_period_end is None
            and self.subscription_id is None
        ):
            return "free_default.new"

        if (
            self.plan.type != Plan.Type.FREE_DEFAULT
            and self.payment_state == Customer.PaymentState.OFF
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
            and self.payment_state == Customer.PaymentState.OK
            and self.subscription_id is not None
        ):
            # There's a paid plan, it's not expired, and there's payments coming.
            return "paid.paying"

        if (
            self.plan.type in (Plan.Type.PAID_PUBLIC, Plan.Type.PAID_PRIVATE)
            and self.current_period_end is not None
            and self.current_period_end > timezone.now()
            and self.payment_state == Customer.PaymentState.OFF
            and self.subscription_id is not None
        ):
            # There's a paid plan, it's not expired, but there's no more payments coming.
            # This Customer can be reactivated.
            return "paid.will_cancel"

        if (
            self.plan.type == Plan.Type.FREE_PRIVATE
            and self.current_period_end is None
            and self.payment_state == Customer.PaymentState.OFF
            and self.subscription_id is None
        ):
            # Free private plan with no expiration date
            return "free_private.indefinite"

        if (
            self.plan.type == Plan.Type.FREE_PRIVATE
            and self.current_period_end is not None
            and self.current_period_end > timezone.now()
            and self.payment_state == Customer.PaymentState.OFF
            and self.subscription_id is None
        ):
            # Free private plan with an expiration date in the future.
            # An expiration date in the past yields free_private.expired.
            return "free_private.will_expire"

        if (
            self.plan.type == Plan.Type.FREE_PRIVATE
            and self.current_period_end is not None
            and self.current_period_end < timezone.now()
            and self.payment_state == Customer.PaymentState.OFF
            and self.subscription_id is None
        ):
            # Free private plan with an expiration date in the past.
            return "free_private.expired"

        if (
            self.plan.type in (Plan.Type.PAID_PUBLIC, Plan.Type.PAID_PRIVATE)
            and self.payment_state == Customer.PaymentState.REQUIRES_PAYMENT_METHOD
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
            and self.payment_state == Customer.PaymentState.REQUIRES_PAYMENT_METHOD
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

    class Meta:
        constraints = [
            # Condition to enforce: If payment_state is not set to off, there must be a subscription_id.
            # Constraint to check: Either payment_state is set to off or there is a subscription_id.
            CheckConstraint(
                check=Q(payment_state="off") | Q(subscription_id__isnull=False),
                name="subscription_payment_state_constraint",
            )
        ]

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


class StripeEvent(models.Model):
    """Stripe Events from webhooks"""

    event_id = models.CharField(max_length=254)

    class Type(models.TextChoices):
        NEW_SUB = "new_sub", "New Subscription"
        RENEW_SUB = "renew_sub", "Renew Subscription"
        PAYMENT_FAIL = "payment_fail", "Payment Failure"
        UPDATE_PAYMENT_METHOD = "update_payment_method", "Update Payment Method"
        FIX_PAYMENT_METHOD = (
            "fix_payment_method",
            "Fix Payment Method",
        )
        CANCEL_SUB = "cancel_sub", "Cancel Subscription"
        REACTIVATE_SUB = "reactivate_sub", "Reactivate Subscription"
        DELETE_SUB = "delete_sub", "Delete Subscription"
        UNKNOWN = "unknown", "Unknown"

    type = models.CharField(max_length=254, blank=True)
    primary = models.BooleanField(
        help_text="Is this the primary event for the event type?", default=False
    )
    payload_type = models.CharField(max_length=254)
    received_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    info = models.JSONField(
        null=True,
        blank=True,
        help_text="For convenience, import information from the body and other sources.",
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
        if self.type:
            return StripeEvent.Type(self.type).label
        else:
            return self.payload_type
