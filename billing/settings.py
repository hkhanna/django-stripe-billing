from django.conf import settings

STRIPE_API_KEY = getattr(settings, "STRIPE_API_KEY", None)  # TODO
APPLICATION_NAME = getattr(settings, "BILLING_APPLICATION_NAME", None)
CHECKOUT_SUCCESS_URL = getattr(settings, "BILLING_CHECKOUT_SUCCESS_URL", None)
CHECKOUT_CANCEL_URL = getattr(settings, "BILLING_CHECKOUT_CANCEL_URL", None)
