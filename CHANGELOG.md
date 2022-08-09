Unreleased
---------------------
- Fix bug in event replay.

0.5.1
---------------------
- Ignore Stripe Events that are processed out of order. This avoids an issue where Stripe sends an old Subscription state after a newer one, clobbering the correct state.
- Admin improvements
- Add long description for Pypi

0.5.0
----------------------
- Automatically retry failed invoices when a customer updates their subscription payment method.
- Fix a bug where if a customer's payment failed and you renewed it, the state was messed up.
- Major refactor that considers the subscription information coming from Stripe authoritative.
- As such, you should no longer listen to any webhooks other than `customer.subscription.*`. All other webhooks will be ignored.
- _Backwards incompatible change_: You should replay the most recent `customer.subscription.*` webhook for all users.

0.4.1
----------------------
- Bugfix: inconsistent generation of `stripe_session_url` in the `BillingMixin`.

0.4.0
----------------------
- Added support for private paid plans. The use case would be grandfathered pricing or custom pricing for customers.
- _Backwards incompatible change_: The URL path and arguments to billing:create-checkout-session have changed.
