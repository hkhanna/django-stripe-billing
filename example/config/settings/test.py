import os

# This isn't needed for now, and it's interfering with pytest logging assertions ("caplog").
# os.environ["LOGLEVEL"] = "CRITICAL"  # Prevent log spew

from .local import *

# Stripe - Don't use the 'mock' key because we want to patch the stripe library in the tests
STRIPE_API_KEY = "testing"
