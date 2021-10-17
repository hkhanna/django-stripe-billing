# billing

`billing` is a Django app to manage Stripe billing plans.

## Installation


1. Add "billing" to your `requirements.txt`
   ```
   ...
   git+https://github.com/hkhanna/billing.git
   ...
   ```
1. You may now need to install it with `pip install -r requirements.txt`.
1. Add "billing" to your INSTALLED_APPS setting like this:
   ```
   INSTALLED_APPS = [
       ...
       'billing',
       ...
   ]
   ```
1. Include the billing URLconf in your project urls.py like this:
   ```
       path('billing/', include('billing.urls')), 
   ```
1. OPTIONAL: Use celery for webhook processing: `pip install celery` and add it to requirements. If you don't install celery, it will process webhooks synchronously.
1. Set the [environment variables](#environment-variables).
1. Run `python manage.py migrate` to create the billing models.
1. Run `python manage.py billing_init`, which will create Customer objects for existing Users. If you don't do this, you may run into errors.
1. Add this to your user admin file:
   ```
   import billing.admin
   ...
   class UserAdmin(DefaultUserAdmin):
   ...
       inlines = [billing.admin.CustomerAdminInline, billing.admin.StripeEventAdminInline]
   ```
1. Once you have [configured Stripe](#stripe-configuration), create the desired billing `Plan`s in the Django admin.
1. Add the `billing.mixins.BillingMixin` to the view where a user might manage their billing (e.g. a "Settings" view).
  - There must be at least one Paid billing plan to use this Mixin.

### Stripe Configuration
1. In your Stripe dashboard, you _must_ configure it to cancel a customer's subscription if all retries for a payment fail.
1. Do not allow the Customer to update their email address in Customer Portal.
1. Do not allow the Customer to update billing information (other than payment method) or view invoice history.
1. Update the branding of Checkout/Portal to match the branding of your site.
1. In your Stripe dashboard, set up a product (with an optional statement descriptor), and set up a price for that product.
1. In the Stripe dashboard, the following webhooks should be set to point to `https://production.url/billing/stripe/webhook/`:
    - `checkout.session.completed` 
    - `invoice.paid`
    - `invoice.payment_failed`
    - `customer.subscription.updated`
    - `customer.subscription.deleted`

### Environment Variables
- `BILLING_STRIPE_API_KEY`: The Stripe API key.
  - **Required**
  - You may use the word `mock` for a mocked Stripe client. This can be useful in local development. You can't use Checkout/Portal, but any other function that calls out to stripe will just call a mock.
  - You must use a real test environment Stripe API key if using Stripe Checkout / Portal while developing locally.
  - Obviously, only use a live environment Stripe API key in production.
- `BILLING_APPLICATION_NAME`: The name of the application.
  - **Required**
  - The Stripe customer metadata will store this in the `application` key.
- `BILLING_CHECKOUT_SUCCESS_URL`
  - **Required**
  - Where Stripe Checkout should redirect on success.
  - This view should parse Django messages.
  - Must be an absolute URL or begin with a `/`.
- `BILLING_CHECKOUT_CANCEL_URL`
  - **Required**
  - Where Stripe Checkout should redirect on cancel.
  - This view should parse Django messages.
  - Must be an absolute URL or begin with a `/`.
- `BILLING_STRIPE_WH_SECRET`
  - Optional
  - If this is set, Stripe webhook processing will verify the webhook signature for authenticity.

## Usage
- `POST` to `billing:create_checkout_session` to create a Stripe Checkout Session.
  - Form data must contain `plan_id` which is the pk of the paid billing plan.
- `POST` to `billing:create_portal_session` to create a Stripe Billing Portal Session.
  - Form data must contain `return_url` which is the URL to go back to once the Customer is done with the Portal. If this is omitted, it defaults to the `LOGIN_REDIRECT_URL`.
- A `BillingMixin` is available in `billing.mixins.BillingMixin`. This defines a `get_context_data(self, **kwargs)` method that returns the following context:
  - `billing_enabled` is a convenience check for whether billing is enabled.
  - `stripe_session_url` for the form button to take you to the Stripe Checkout/Portal.
  - `stripe_session_button_text` text for the button describing what it will do.
  - `billing_state_note` describes basic info about the Customer's current subscription status.
  - `current_plan` the the instance of the Customer's Plan. `current_plan.name` and `current_plan.display_price` are useful if you want to display those things to the user.
  - `stripe_session_type` is either `checkout` or `portal` or None (if it's not showing a Stripe url at all).
  - `paid_plan_id` is the pk of the first Paid Plan found in the database. It's only available if the user can sign up for a new paid plan.
- Look at the example app for more details on how to use it.

### Things to Know
- The app should automatically create a Default Free plan during installation.
- Users should have a first name, last name and email.
- Deleting a User or setting User.is_active to false will cancel any active Stripe subscriptions.
- Updating a User's first name, last name or email will update it on Stripe.
- The app will assign a stripe `customer_id` to the `Customer` the first time the `User` requests to create a subscription. Before that, the `user.customer.customer_id` will be `null`.
- All paid plans must have a Stripe `price_id`.
- The app will automaticaly create a free_default plan the first time its needed if one doesn't exist and it will default to whatever defaults are specified in the Limits. You can modify the plan or even delete it, but there must always be 1 free_default plan and if there is not, the app will create it the next time it needs it.
- A user with a paid plan that has expired will drop to the limits set in the free_default plan. 
- A user with a free private (i.e. staff) plan that has expired will drop to the limits set in the free_default plan. A user with a free private plan where there
  is no current_period_end set will be treated as NO expiration date on the plan and will continue to enjoy the free private plan indefinitely.

## Local Development

## Running the Test Suite

1. `python3 -m venv .venv`
1. `source .venv/bin/activate`
1. `pip install -r requirements.txt`
1. `py.test`

### Running the example app
1. `python3 -m venv .venv`
1. `source .venv/bin/activate`
1. `pip install -r requirements.txt`
1. `python3 manage.py migrate`
1. `python3 manage.py createsuperuser`
1. `python3 manage.py runserver`
1. OPTIONAL: Use celery for webhook processing: `pip install celery`. If you don't install celery, it will process webhooks synchronously.
1. If you are going to run the Stripe Checkout and Checkout Portal flow, you need to set `BILLING_STRIPE_API_KEY` and setup a Paid plan in the admin with
   a Stripe `price_id` from the real Stripe testing environment.

#### Simulating Webhooks
1. [Install the Stripe CLI](https://stripe.com/docs/stripe-cli). It's simple on Linux, just extract the `tar.gz` file and put the file in your `PATH`.
1. Create the file in `~/.config/stripe/config.toml` with this format:
```
  [default]
    device_name = "<choose a name>"
    test_mode_api_key = "<test environment secret or restricted key>"
    test_mode_publishable_key = "<test environment publishable key>"
```
1. Run `stripe listen --forward-to localhost:8000/billing/stripe/webhook/`
1. If you want to re-send an event: `stripe events resend evt_<evtid>`

### Deleting Test Data

From time to time, you may want to delete all Stripe test data via the dashboard. If you do that, your API keys should remain the same and won't need to be updated. But you will need to create a product and price in the Stripe dashboard and update any paid `Plan` instances to reflect the new `price_ids`.

## Architecture and Models

There are five models in this application: `Limit`, `Plan`, `PlanLimit`, `Customer`, and `StripeEvent`. We'll focus on the first four, as `StripeEvent` is for webhook processing.

### Limit, Plan, and PlanLimit Models

The `Limit` model defines the specific features of your application that are regulated by billing.
For example, if you can send emails via your application, you might have a `Limit` named `Max Emails`
to limit how many emails a user can send.

There are 1 or more `Plans` that have a many-to-many relationship with `Limit` through the `PlanLimit` model.
It's through those relationships you set the limits for the various plans. For example, if you have a free plan
that can send 1 email per day and paid plan that can send 5 emails per day, each of those plans would have a M2M
relationship with the `Limit` named `Max Emails`. In the through model, `PlanLimit` you set the value of the `Limit` for that `Plan` in an `InlineAdmin`.

So far, so good. But what if your `Plan` forgets to set one of the `Limits`? What's the value of the `Limit` for that `Plan`? For that reason, each `Limit` also defines a `default` value that is used if a `Plan` hasn't set
that particular `Limit`.

`Plans` can be one of three types: `free_default`, `free_private`, and `paid_public`.

- There must at all times be exactly one `free_default Plan`. This is the plan that a user defaults to when they create an account. Or if their credit card doesn't go through. It's the 'fallback' plan when no other plan has been selected. If you have a free tier, it would be sensible to configure it as this plan. This plan must be free and does not interface with Stripe.
- A `free_private` plan is a plan that you can assign staff to have free access at a paid level or with some higher than normal limits.
- A `paid_public` plan must have a corresponding `price_id` in Stripe and is the only type of `Plan` that interfaces with Stripe.

**`free_default` versus `Limit` defaults**. A source of confusion can be what is the difference between the limit values configured in the `free_default Plan` and the defaults set on the `Limit` instances themselves? The `Limit` defaults attach when _any_ `Plan` does not define a value for _that particular `Limit`_. There has to be some value for a `Limit` in, say, a paid `Plan` even when that `Plan` does not specifically define the `Limit`.

The `free_default Plan` is simply another `Plan` that _may or may not_ define `Limits`. If it does not, then functionally there is no difference between the two since the plan will fall back to the defaults set on the `Limits`. If it does specifically define values for `Limits`, those values as defined become what a user falls back to when their credit card expires or they cancel their paid subscription.

Practically speaking, the real reason `Limits` have defaults is because there is no simple way to enforce that a `Plan` will have a many-to-many relationship with every single `Limit` defined in the database. If we could enforce that easily, there would be no need for defaults on the `Limit` instances themsleves.

There must always be one and only one `free_default Plan`. It's created in a data migration and this condition is enforced via a database constraint.

A `paid_public` plan is subscribable by users. The others are not.

### Customer Model

For non-paid plans, the `Customer` model is pretty straightforward. The only attributes of real significance is the linked `Plan`, the `customer_id`, which is generated by Stripe the first time a User subscribes, and `current_period_end`.

`current_period_end` is when the `Customer's` `Plan` will end if not renewed. After this time, the `Customer` falls back to the `free_default` Plan. If a `Customer`'s `Plan` is of type `free_default`, the `Customer` cannot have a `current_period_end` since that wouldn't make any sense, i.e., what would the `Customer` fall back to.

Every `User` must have a related `Customer`. If the `User` does not have a `Customer`, it will automatically create one on save.

For paid `Plans`, things are a little more complicated. Before we dive into it, first a brief primer on Stripe's subscription model.

#### Primer on Stripe's Subscription Model

Stripe's Subscription model can have a `status` of: `incomplete`, `incomplete_expired`, `active`, `past_due`, `canceled`, `trialing`, or `unpaid`.

`incomplete` means a Customer's credit card was attached to them and a subscription was created but the card was declined. The Customer has 23 hours to fix it and if they don't, the subscription gets `incomplete_expired` which is functionally the same as `canceled`. I.e., no invoices will be created or paid in those states. We don't use this because we just ignore incomplete subscriptions and let them expire. A user creates a fresh one
in the Checkout if they come back.

`past_due` occurs when a recurring payment fails. The payment is retried according to settings in the Stripe dashboard. Once Stripe gives up, the status changes to `canceled`.

We don't use `trialing`, which is useful if you want to have trials where the customer puts in their credit card before the trial. We don't use `unpaid`, which is an alternative way of handling permanent recurring payment failures instead of making the status `cancelled`.

#### Back to Our Customer Model

There is a field on Customer called `payment_state` that is a function of the Stripe subscription state.

There is a property on Customer called `state` that is calculated from all the other attributes on Customer. These can be used for easy representation of Customer state on the frontend.

You can see what they are in `billing.models`. This can be improved and should probably operate more like a state machine.

## Possible Future Enhancements

- Multiple paid plans. Will need to write tests to upgrade/downgrade plans and those should be their own endpoints probably.
- Paid private plans, e.g., for grandfathering in pricing.
- Grace periods for expired payments
- Trial periods
- Coupons for friends
- "When a subscription changes to past_due, your webhook script could email you about the problem so you can reach out to the customer, or the script could email the customer directly, asking them to update their payment details." Although maybe we could rely on this: https://stripe.com/docs/billing/subscriptions/overview#emails
- Interstitial pages to wait for webhooks. Imagine you do the checkout flow then it redirects you to a spinner page that polls an endpoint for where to go next. If the webhook hasn't been received redirect back for 3 seconds. If it has, redirect to the success page.
- Move away from Portal. Maybe wouldn't be terrible since all the heavy lifting happens in webhook processing. The interstitial pages would be useful here. 
