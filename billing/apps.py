from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured
from . import settings


class BillingConfig(AppConfig):
    name = "billing"

    def ready(self):
        import billing.signals

        for setting in (
            "STRIPE_API_KEY",
            "APPLICATION_NAME",
            "CHECKOUT_SUCCESS_URL",
            "CHECKOUT_CANCEL_URL",
        ):
            missing = []
            if getattr(settings, setting) is None:
                missing.append(setting)
            if len(missing) > 0:
                missing = ", ".join(missing)
                raise ImproperlyConfigured(f"{missing} must be configured.")
