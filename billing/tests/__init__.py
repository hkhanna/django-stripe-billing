try:
    from celery import Celery

    app = Celery("billing_test")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()
except ImportError:
    pass
