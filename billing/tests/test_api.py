"""Tests for the API"""
import json
from datetime import timedelta
from unittest import mock
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from .. import models, factories, serializers

User = get_user_model()

# There are 6 types of tests when it comes to billing:
#
# One important rule: you may not call another app's URL namespace from these tests.
#
# 1. Django-y things like signals and model constraints.
# A customer is automatically created if a user does not have one, and it accomplishes this via signals.
# We also have some model constraints we want to test.
#
# 2. Customer information returned via the API.
# Serialized information about the Customer must be returned on various endpoints. While we can test the
# serializer here, the Customer information should be returned by an endpoint outside this app (like a user
# settings endpoint), so there should also be at least one test in whatever app contains the User model ensuring
# that Customer information comes through where its needed.
#
# 3. Limits (see test_limits.py)
#
# 4. Users interacting with subscriptions for the first time.
# Like upgrading to a paid plan or canceling the paid plan.
#
# 5. Stripe webhook processing.
# Making sure that the right Stripe webhooks are processed in the right way.
#
# 6. Users taking action on the website due to a webhook.
# If a webhook comes in that says the credit card is expired, a user will come back to the website to take action.
# We don't test these since they're substantially captured by test cases in type 4. For example, if a credit card
# is declined on renewal, it looks very much like a credit card being declined initially.


@patch("billing.services.stripe")
class CustomerSerializerAPITest(APITestCase):
    """Tests related to the Customer serializer."""

    def test_customer_serializer(self, *args):
        """Customer serializer returns expected information"""
        user = factories.UserFactory()
        serializer = serializers.CustomerSerializer(instance=user.customer)
        self.assertJSONEqual(
            json.dumps(serializer.data),
            {
                "current_period_end": None,
                "payment_state": models.Customer.PaymentState.OFF,
                "cc_info": None,
                "state": "free_default.new",
                "plan": {
                    "name": "Default (Free)",
                    "display_price": 0,
                    "type": models.Plan.Type.FREE_DEFAULT,
                    "limits": {},
                },
            },
        )

    def test_customer_paying_serializer(self, *args):
        """Paying customer serializer returns expected information"""
        user = factories.UserFactory(paying=True)
        plan_limit1, plan_limit2 = factories.PlanLimitFactory.create_batch(
            plan=user.customer.plan, size=2
        )
        limit3 = (
            factories.LimitFactory()
        )  # Create 1 more limit so we can test that default comes through when PlanLimit not set.
        free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
        df_planlimit = factories.PlanLimitFactory(
            plan=free_default_plan, value=50, limit__name="Limit used by free_default"
        )

        serializer = serializers.CustomerSerializer(instance=user.customer)
        self.assertJSONEqual(
            json.dumps(serializer.data),
            {
                "current_period_end": user.customer.current_period_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "payment_state": models.Customer.PaymentState.OK,
                "cc_info": user.customer.cc_info,
                "state": "paid.paying",
                "plan": {
                    "name": user.customer.plan.name,
                    "display_price": user.customer.plan.display_price,
                    "type": models.Plan.Type.PAID_PUBLIC,
                    "limits": {
                        plan_limit1.limit.name: plan_limit1.value,
                        plan_limit2.limit.name: plan_limit2.value,
                        limit3.name: limit3.default,
                        "Limit used by free_default": df_planlimit.limit.default,
                    },
                },
            },
        )

    def test_customer_paying_expired_serializer(self, *args):
        """Paying customer serializer with expired current_period_end (we missed a webhook)
        should return free_default information"""
        user = factories.UserFactory(
            paying=True,
            customer__payment_state=models.Customer.PaymentState.OFF,
            customer__current_period_end=factories.fake.past_datetime(
                tzinfo=timezone.utc
            ),
        )
        plan_limit1, plan_limit2 = factories.PlanLimitFactory.create_batch(
            plan=user.customer.plan, size=2
        )
        limit3 = (
            factories.LimitFactory()
        )  # Create 1 more limit so we can test that default comes through when PlanLimit not set.
        free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
        df_planlimit = factories.PlanLimitFactory(
            plan=free_default_plan, value=50, limit__name="Limit used by free_default"
        )

        serializer = serializers.CustomerSerializer(instance=user.customer)
        self.assertJSONEqual(
            json.dumps(serializer.data),
            {
                "current_period_end": user.customer.current_period_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "payment_state": models.Customer.PaymentState.OFF,
                "cc_info": user.customer.cc_info,
                "state": "free_default.canceled.missed_webhook",
                "plan": {
                    "name": free_default_plan.name,
                    "display_price": free_default_plan.display_price,
                    "type": models.Plan.Type.FREE_DEFAULT,
                    "limits": {
                        plan_limit1.limit.name: plan_limit1.limit.default,
                        plan_limit2.limit.name: plan_limit2.limit.default,
                        limit3.name: limit3.default,
                        "Limit used by free_default": df_planlimit.value,
                    },
                },
            },
        )

    def test_customer_paying_no_date_serializer(self, *args):
        """Paying customer serializer with None for current_period_end should return free_default information.
        This can only happen if someone signs up but their signup was incomplete because their credit card was not
        accepted."""
        user = factories.UserFactory(
            paying=True,
            customer__payment_state=models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD,
            customer__current_period_end=None,
        )
        plan_limit1, plan_limit2 = factories.PlanLimitFactory.create_batch(
            plan=user.customer.plan, size=2
        )
        limit3 = (
            factories.LimitFactory()
        )  # Create 1 more limit so we can test that default comes through when PlanLimit not set.
        free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
        df_planlimit = factories.PlanLimitFactory(
            plan=free_default_plan, value=50, limit__name="Limit used by free_default"
        )

        serializer = serializers.CustomerSerializer(instance=user.customer)
        self.assertJSONEqual(
            json.dumps(serializer.data),
            {
                "current_period_end": None,
                "payment_state": models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD,
                "cc_info": user.customer.cc_info,
                "state": "free_default.incomplete.requires_payment_method",
                "plan": {
                    "name": free_default_plan.name,
                    "display_price": free_default_plan.display_price,
                    "type": models.Plan.Type.FREE_DEFAULT,
                    "limits": {
                        plan_limit1.limit.name: plan_limit1.limit.default,
                        plan_limit2.limit.name: plan_limit2.limit.default,
                        limit3.name: limit3.default,
                        "Limit used by free_default": df_planlimit.value,
                    },
                },
            },
        )

    def test_customer_free_private_expired_serializer(self, *args):
        """Free private free plan with an expired current_period_end should return the free_default plan information."""
        user = factories.UserFactory(
            customer__plan=factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE),
            customer__current_period_end=factories.fake.past_datetime(
                tzinfo=timezone.utc
            ),
        )
        plan_limit1, plan_limit2 = factories.PlanLimitFactory.create_batch(
            plan=user.customer.plan, size=2
        )
        limit3 = (
            factories.LimitFactory()
        )  # Create 1 more limit so we can test that default comes through when PlanLimit not set.
        free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
        df_planlimit = factories.PlanLimitFactory(
            plan=free_default_plan, value=50, limit__name="Limit used by free_default"
        )

        serializer = serializers.CustomerSerializer(instance=user.customer)
        self.assertJSONEqual(
            json.dumps(serializer.data),
            {
                "current_period_end": user.customer.current_period_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "payment_state": models.Customer.PaymentState.OFF,
                "cc_info": None,
                "state": "free_private.expired",
                "plan": {
                    "name": free_default_plan.name,
                    "display_price": free_default_plan.display_price,
                    "type": models.Plan.Type.FREE_DEFAULT,
                    "limits": {
                        plan_limit1.limit.name: plan_limit1.limit.default,
                        plan_limit2.limit.name: plan_limit2.limit.default,
                        limit3.name: limit3.default,
                        "Limit used by free_default": df_planlimit.value,
                    },
                },
            },
        )

    def test_customer_free_private_no_date_serializer(self, *args):
        """Free private plan with None for current_period_end should still return free private information."""
        user = factories.UserFactory(
            customer__plan=factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE),
            customer__current_period_end=None,
        )
        plan_limit1, plan_limit2 = factories.PlanLimitFactory.create_batch(
            plan=user.customer.plan, size=2
        )
        limit3 = (
            factories.LimitFactory()
        )  # Create 1 more limit so we can test that default comes through when PlanLimit not set.
        free_default_plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
        df_planlimit = factories.PlanLimitFactory(
            plan=free_default_plan, value=50, limit__name="Limit used by free_default"
        )

        serializer = serializers.CustomerSerializer(instance=user.customer)
        self.assertJSONEqual(
            json.dumps(serializer.data),
            {
                "current_period_end": None,
                "payment_state": models.Customer.PaymentState.OFF,
                "cc_info": None,
                "state": "free_private.indefinite",
                "plan": {
                    "name": user.customer.plan.name,
                    "display_price": user.customer.plan.display_price,
                    "type": models.Plan.Type.FREE_PRIVATE,
                    "limits": {
                        plan_limit1.limit.name: plan_limit1.value,
                        plan_limit2.limit.name: plan_limit2.value,
                        limit3.name: limit3.default,
                        "Limit used by free_default": df_planlimit.limit.default,
                    },
                },
            },
        )


@patch("billing.services.stripe")
class SubscriptionAPITest(APITestCase):
    """This contains tests type 4 from above."""

    def test_create_subscription(self, *args):
        """Create Subscription endpoint succeeds and should set the customer_id, plan, current_period_end,
        payment_state and card_info"""
        current_period_end = timezone.now() + timedelta(days=30)
        cc_info = factories.cc_info()
        args[0].Customer.create.return_value.id = factories.id("cus")
        args[0].Subscription.create.return_value.id = "sub_paid"
        args[0].Subscription.create.return_value.status = "active"
        args[
            0
        ].Subscription.create.return_value.current_period_end = (
            current_period_end.timestamp()
        )
        args[0].PaymentMethod.attach.return_value.card = cc_info
        paid_plan = factories.PlanFactory(paid=True)

        self.user = factories.UserFactory()
        self.client.force_login(self.user)

        url = reverse("billing_api:create-subscription")
        payload = {
            "payment_method_id": factories.id("payment"),
            "plan_id": paid_plan.id,
        }
        response = self.client.post(url, payload)
        self.assertEqual(201, response.status_code)
        args[0].Customer.create.assert_called_once()
        args[0].Subscription.create.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(paid_plan, self.user.customer.plan)
        self.assertEqual(
            models.Customer.PaymentState.OK, self.user.customer.payment_state
        )
        self.assertEqual(
            current_period_end.timestamp(),
            self.user.customer.current_period_end.timestamp(),
        )
        self.assertEqual("sub_paid", self.user.customer.subscription_id)
        self.assertJSONEqual(json.dumps(self.user.customer.cc_info), cc_info)
        self.assertEqual("paid.paying", self.user.customer.state)

    def test_create_subscription_customer_id_exists(self, *args):
        """Creating a Subscription should not change the customer_id or create a new Stripe customer
        if the Customer already has a customer_id"""
        current_period_end = timezone.now() + timedelta(days=30)
        cc_info = factories.cc_info()
        args[0].Subscription.create.return_value.id = "sub_paid"
        args[0].Subscription.create.return_value.status = "active"
        args[
            0
        ].Subscription.create.return_value.current_period_end = (
            current_period_end.timestamp()
        )
        args[0].PaymentMethod.attach.return_value.card = cc_info
        paid_plan = factories.PlanFactory(paid=True)

        self.user = factories.UserFactory(customer__customer_id="cus_xyz")
        self.client.force_login(self.user)

        url = reverse("billing_api:create-subscription")
        payload = {
            "payment_method_id": factories.id("payment"),
            "plan_id": paid_plan.id,
        }
        response = self.client.post(url, payload)
        self.assertEqual(201, response.status_code)
        args[0].Customer.create.assert_not_called()
        args[0].Subscription.create.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual("cus_xyz", self.user.customer.customer_id)
        self.assertEqual(paid_plan, self.user.customer.plan)
        self.assertEqual(
            models.Customer.PaymentState.OK, self.user.customer.payment_state
        )
        self.assertEqual(
            current_period_end.timestamp(),
            self.user.customer.current_period_end.timestamp(),
        )
        self.assertEqual("sub_paid", self.user.customer.subscription_id)
        self.assertJSONEqual(json.dumps(self.user.customer.cc_info), cc_info)
        self.assertEqual("paid.paying", self.user.customer.state)

    def test_create_subscription_failed(self, *args):
        """Create Subscription endpoint attaches the payment method to the Customer but the charge fails. Should set
        the customer's payment_state and state but the plan and current_period_end should not be modified."""
        cc_info = factories.cc_info()
        args[0].Customer.create.return_value.id = factories.id("cus")
        args[0].Subscription.create.return_value.id = "sub_paid"
        args[0].Subscription.create.return_value.status = "incomplete"
        args[
            0
        ].Subscription.create.return_value.latest_invoice.payment_intent.status = (
            "requires_payment_method"
        )
        args[0].PaymentMethod.attach.return_value.card = cc_info

        self.user = factories.UserFactory()
        self.client.force_login(self.user)

        paid_plan = factories.PlanFactory(paid=True)
        url = reverse("billing_api:create-subscription")
        payload = {
            "payment_method_id": factories.id("payment"),
            "plan_id": paid_plan.id,
        }
        response = self.client.post(url, payload)
        self.assertEqual(400, response.status_code)
        args[0].Customer.create.assert_called_once()
        args[0].Subscription.create.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(paid_plan, self.user.customer.plan)
        self.assertEqual(
            models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD,
            self.user.customer.payment_state,
        )
        self.assertEqual(None, self.user.customer.current_period_end)
        self.assertEqual("sub_paid", self.user.customer.subscription_id)
        self.assertJSONEqual(json.dumps(self.user.customer.cc_info), cc_info)
        self.assertEqual(
            "free_default.incomplete.requires_payment_method", self.user.customer.state
        )

    def test_create_subscription_failed_cure(self, *args):
        """A card initially declined can be cured within 23 hours"""
        self.user = factories.UserFactory(
            paying=True,
            customer__subscription_id="sub_1",
            customer__payment_state=models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD,
        )
        self.client.force_login(self.user)

        new_cc_info = {
            "brand": "visa",
            "last4": "1111",
            "exp_month": 11,
            "exp_year": 2017,
        }
        mock_period_end = timezone.now() + timedelta(days=30)
        args[0].PaymentMethod.attach.return_value.card = new_cc_info
        args[0].Invoice.list.return_value = {
            "data": [{"id": "inv_id", "status": "open"}]
        }
        args[0].Invoice.pay.return_value = {
            "status": "paid",
            "lines": {"data": [{"period": {"end": mock_period_end.timestamp()}}]},
        }

        url = reverse("billing_api:cure-failed-card")
        payload = {"payment_method_id": "abc"}
        response = self.client.post(url, payload)
        self.assertEqual(201, response.status_code)
        args[0].PaymentMethod.attach.assert_called_once()
        args[0].Subscription.modify.assert_called_once()
        args[0].Invoice.list.assert_called_once()
        args[0].Invoice.pay.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(
            models.Customer.PaymentState.OK, self.user.customer.payment_state
        )
        self.assertEqual(models.Plan.Type.PAID_PUBLIC, self.user.customer.plan.type)
        self.assertEqual("sub_1", self.user.customer.subscription_id)
        self.assertJSONEqual(json.dumps(self.user.customer.cc_info), new_cc_info)
        self.assertEqual(
            mock_period_end.timestamp(),
            self.user.customer.current_period_end.timestamp(),
        )
        self.assertEqual("paid.paying", self.user.customer.state)

    def test_create_subscription_twice(self, *args):
        """Attempting to create a subscription when one is active fails"""
        # If current_period_end is in the future and payment_state is off, they should be re-activating, not creating a subscription.
        self.user = factories.UserFactory(
            paying=True, customer__payment_state=models.Customer.PaymentState.OFF
        )
        self.client.force_login(self.user)

        url = reverse("billing_api:create-subscription")
        payload = {"payment_method_id": "abc", "plan_id": self.user.customer.plan.id}
        response = self.client.post(url, payload)
        self.assertContains(response, "has a subscription", status_code=400)

    def test_nonpublic_plan(self, *args):
        """Billing Plans that are not public cannot be subscribed to via the API"""
        plan = factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE)

        self.user = factories.UserFactory()
        self.client.force_login(self.user)

        url = reverse("billing_api:create-subscription")
        payload = {"payment_method_id": "abc", "plan_id": plan.id}
        response = self.client.post(url, payload)
        self.assertContains(response, "plan does not exist", status_code=400)
        args[0].Subscription.create.assert_not_called()

    def test_cancel_subscription(self, *args):
        """Canceling a subscription sets expecting_webhook_since
        but otherwise does not affect the billing plan."""
        self.user = factories.UserFactory(paying=True)
        self.client.force_login(self.user)
        url = reverse("billing_api:cancel-subscription")
        response = self.client.post(url)
        self.assertEqual(201, response.status_code)
        args[0].Subscription.modify.assert_called_once()
        self.user.customer.refresh_from_db()
        self.assertEqual("paid.paying", self.user.customer.state)
        self.assertIsNotNone(self.user.customer.expecting_webhook_since)

    def test_cancel_subscription_error(self, *args):
        """Cancelling a subscription with payment_state set to off will 400"""
        self.user = factories.UserFactory(
            paying=True, customer__payment_state=models.Customer.PaymentState.OFF
        )
        self.client.force_login(self.user)
        url = reverse("billing_api:cancel-subscription")
        response = self.client.post(url)
        self.assertContains(
            response, "No active subscription to cancel", status_code=400
        )

    def test_reactivate_subscription(self, *args):
        """Reactivating a subscription that will be canceled before the end of the billing cycle"""
        self.user = factories.UserFactory(
            paying=True, customer__payment_state=models.Customer.PaymentState.OFF
        )
        self.client.force_login(self.user)
        subscription_id = self.user.customer.subscription_id

        url = reverse("billing_api:reactivate-subscription")
        response = self.client.post(url)
        self.assertEqual(201, response.status_code)
        self.user.customer.refresh_from_db()
        self.assertEqual(
            models.Customer.PaymentState.OK, self.user.customer.payment_state
        )
        self.assertEqual(subscription_id, self.user.customer.subscription_id)
        args[0].Subscription.modify.assert_called_once()
        self.assertEqual("paid.paying", self.user.customer.state)

    def test_reactivate_subscription_error(self, *args):
        """Reactivating a subscription that will be canceled before the end of the billing cycle errors
        if there's an active subscription or one that is already canceled"""
        self.user = factories.UserFactory(
            paying=True, customer__payment_state=models.Customer.PaymentState.OFF
        )
        self.client.force_login(self.user)

        url = reverse("billing_api:reactivate-subscription")

        # First, the sub is already canceled but we missed the webhook
        self.user.customer.current_period_end = timezone.now() - timedelta(days=10)
        self.user.customer.save()
        self.assertEqual(
            "free_default.canceled.missed_webhook", self.user.customer.state
        )
        response = self.client.post(url)
        self.assertEqual(400, response.status_code)

        # The payment is not off
        self.user.customer.current_period_end = timezone.now() + timedelta(days=10)
        self.user.customer.payment_state = models.Customer.PaymentState.OK
        self.user.customer.save()
        self.assertEqual("paid.paying", self.user.customer.state)
        response = self.client.post(url)
        self.assertEqual(400, response.status_code)

        # There was never any subscription
        self.user.customer.plan = factories.PlanFactory(
            type=models.Plan.Type.FREE_DEFAULT
        )
        self.user.customer.current_period_end = None
        self.user.customer.payment_state = models.Customer.PaymentState.OFF
        self.user.customer.subscription_id = None
        self.user.customer.save()
        self.assertEqual("free_default.new", self.user.customer.state)
        response = self.client.post(url)
        self.assertEqual(400, response.status_code)

    def test_replace_card(self, *args):
        """Replace a credit card for an active subscription"""
        self.user = factories.UserFactory(paying=True)
        self.client.force_login(self.user)

        new_cc_info = {
            "brand": "visa",
            "last4": "1111",
            "exp_month": 11,
            "exp_year": 2017,
        }
        args[0].PaymentMethod.attach.return_value.card = new_cc_info
        url = reverse("billing_api:replace-card")
        payload = {"payment_method_id": "abc"}
        response = self.client.post(url, payload)
        self.assertEqual(201, response.status_code)
        args[0].PaymentMethod.attach.assert_called_once()
        args[0].Subscription.modify.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(
            models.Customer.PaymentState.OK, self.user.customer.payment_state
        )
        self.assertJSONEqual(json.dumps(self.user.customer.cc_info), new_cc_info)
