import os

os.environ["LOGLEVEL"] = "CRITICAL"  # Prevent log spew

from .local import *

# Stripe - Don't use the 'mock' key because we want to patch the stripe library in the tests
STRIPE_API_KEY = "testing"
