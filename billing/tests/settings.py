import os
import os.path

BASE_DIR = os.path.dirname(__file__)
DEBUG = False
SECRET_KEY = "not a real secret"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "billing",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "billing.tests.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
    },
]


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "db.sqlite3",
        "ATOMIC_REQUESTS": False,
    }
}

# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Billing
# Stripe - Don't use the 'mock' key because we want to patch the stripe library in the tests
BILLING_STRIPE_API_KEY = "testing"
BILLING_STRIPE_WH_SECRET = None
BILLING_APPLICATION_NAME = "example"
BILLING_CHECKOUT_SUCCESS_URL = "/accounts/profile/"
BILLING_CHECKOUT_CANCEL_URL = "/accounts/profile/"

# Celery - Will only be used if you pip install celery
# https://docs.celeryproject.org/en/stable/getting-started/brokers/redis.html
CELERY_BROKER_URL = None
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_TIME_LIMIT = 60  # Raise exception after 60 seconds.
CELERY_WORKER_TASK_LOG_FORMAT = "[%(name)s] at=%(levelname)s timestamp=%(asctime)s processName=%(processName)s task_id=%(task_id)s task_name=%(task_name)s %(message)s"
CELERY_WORKER_LOG_FORMAT = "[%(name)s] at=%(levelname)s timestamp=%(asctime)s processName=%(processName)s %(message)s"
CELERY_WORKER_LOG_COLOR = False
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
