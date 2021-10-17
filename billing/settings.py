from django.conf import settings

STRIPE_API_KEY = getattr(settings, "BILLING_STRIPE_API_KEY", None)
APPLICATION_NAME = getattr(settings, "BILLING_APPLICATION_NAME", None)
CHECKOUT_SUCCESS_URL = getattr(settings, "BILLING_CHECKOUT_SUCCESS_URL", None)
CHECKOUT_CANCEL_URL = getattr(settings, "BILLING_CHECKOUT_CANCEL_URL", None)
STRIPE_WH_SECRET = getattr(settings, "BILLING_STRIPE_WH_SECRET", None)

LOGIN_REDIRECT_URL = getattr(settings, "LOGIN_REDIRECT_URL")
