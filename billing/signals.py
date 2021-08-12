from django.dispatch import receiver
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import pre_save, post_save, pre_delete

from . import models, services


@receiver(pre_save, sender=settings.AUTH_USER_MODEL)
def user_pre_save_signal(sender, instance, **kwargs):
    """If a User's name or email is changed, update it in Stripe."""
    if hasattr(instance, "customer") and instance.customer.customer_id:
        User = get_user_model()
        orig = User.objects.get(pk=instance.pk)
        if (
            orig.first_name != instance.first_name
            or orig.last_name != instance.last_name
            or orig.email != instance.email
        ):
            name = f"{instance.first_name} {instance.last_name}"
            services.stripe_modify_customer(instance, name=name, email=instance.email)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def user_post_save_signal(sender, instance, **kwargs):
    """Actions to take on the Customer instance when a User is saved:
    - Users must always have a related Customer instance. If there isn't one, create it.
    - If User.is_active is False, deactivate any active Stripe subscriptions.
    - Save the Customer anytime the User is saved."""
    if not hasattr(instance, "customer"):
        default_plan, _ = models.Plan.objects.get_or_create(
            type=models.Plan.Type.FREE_DEFAULT,
            defaults={"name": "Default (Free)", "display_price": 0},
        )
        models.Customer.objects.create(user=instance, plan=default_plan)
    if (
        not instance.is_active
        and instance.customer.payment_state == models.Customer.PaymentState.OK
    ):
        # Cancel Stripe subscription if the user is being soft deleted.
        services.stripe_cancel_subscription(instance.customer.subscription_id)
        instance.customer.payment_state = models.Customer.PaymentState.OFF
    instance.customer.save()


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def user_hard_delete_signal(sender, instance, **kwargs):
    """Cancel Stripe subscription, if any, when a User is hard deleted."""
    if (
        hasattr(instance, "customer")
        and instance.customer.payment_state == models.Customer.PaymentState.OK
    ):
        # Cancel the Stripe subscription if the user is being hard deleted
        services.stripe_cancel_subscription(instance.customer.subscription_id)
