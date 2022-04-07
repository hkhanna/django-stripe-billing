Unreleased
----------------------
- Automatically retry failed invoices when a customer updates their subscription payment method.
- Fix a bug where if a customer's payment failed and you renewed it, the state was messed up.
- You should no longer listen to any webhooks other than `customer.subscription.*`. All other webhooks will be ignored.

0.4.1
----------------------
- Bugfix: inconsistent generation of `stripe_session_url` in the `BillingMixin`.

0.4.0
----------------------
- Added support for private paid plans. The use case would be grandfathered pricing or custom pricing for customers.
- _Backwards incompatible change_: The URL path and arguments to billing:create-checkout-session have changed.
