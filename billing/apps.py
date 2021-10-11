from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured
from . import settings


class BillingConfig(AppConfig):
    name = "billing"

    def ready(self):
        import billing.signals

        for setting in ("STRIPE_API_KEY", "APPLICATION_NAME"):
            if getattr(settings, setting) is None:
                raise ImproperlyConfigured(f"Must set {setting} setting")
