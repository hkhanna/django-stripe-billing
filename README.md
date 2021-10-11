# billing

`billing` is a Django app to manage billing plans for software-as-a-service.

## Installation

1. Add "billing" to your `requirements.txt`

   ```
   git+https://github.com/hkhanna/billing.git
   ```

1. Add "billing" to your INSTALLED_APPS setting like this:

   ```
       INSTALLED_APPS = [
           ...
           'billing',
       ]
   ```

1. Include the billing URLconf in your project urls.py like this:

   ```
       path('billing/', include('billing.urls.checkout')),
       ... OR ...
       path('billing/', include('billing.urls.api')),
   ```

1. If you are using both checkout and API urls, you will need to give them a unique namespace:

   ```
       path('billing/', include('billing.urls.checkout', namespace="checkout")),
       path('billing/', include('billing.urls.api', namespace="api")),
   ```

1. If you are using the `billing.urls.api` views, you must have Django REST Framework installed.
1. Set the configuration variables (see below).
1. Run `python manage.py migrate` to create the billing models.
1. Run `python manage.py billing_init`, which will create Customer objects for existing Users. If you don't do this, you may run into errors.
1. Add this to your user admin file:

   ```
   import billing.admin
   ...
   class UserAdmin(DefaultUserAdmin):
   ...
       inlines = [billing.admin.CustomerAdminInline]
   ```

## Configuration

- `BILLING_STRIPE_API_KEY`: The Stripe API key.
  - **Required**
  - Use the word "mock" for a mocked Stripe client.
  - You can also use a test Stripe API key.
  - Obviously, only use a live environment Stripe API key in production.
- `BILLING_APPLICATION_NAME`: The name of the application.
  - **Required**
  - The Stripe customer metadata will store this in the `application` key.
- `BILLING_CHECKOUT_SUCCESS_URL`
  - Required only if you use the Stripe Checkout views.
  - This view should parse Django messages.
  - Must be an absolute URL or begin with a `/`.
- `BILLING_CHECKOUT_CANCEL_URL`
  - Required only if you use the Stripe Checkout views.
  - This view should parse Django messages.
  - Must be an absolute URL or begin with a `/`.

## Running the example app

1. `python3 -m venv .venv`
1. `source .venv/bin/activate`
1. `pip install -r requirements.txt`
1. OPTIONAL: Use celery for webhook processing: `pip install celery`. If you don't install celery, it will process webhooks synchronously.
1. `python3 manage.py migrate`
1. `python3 manage.py createsuperuser`
1. `python3 manage.py runserver`
1. If you are going to run the non-API Stripe Checkout and Checkout Portal flow, you need to set `STRIPE_API_KEY` and setup a Paid plan in the admin with
   a Stripe `price_id` from the real Stripe testing environment.

## Running the Test Suite

1. `python3 -m venv .venv`
1. `source .venv/bin/activate`
1. `pip install -r requirements.txt`
1. OPTIONAL: Use celery for webhook processing: `pip install celery`. If you don't install celery, it will process webhooks synchronously.
1. `py.test`

## Deployment to Heroku

1. Add `STRIPE_API_KEY` to the environment variables.
1. In your Stripe dashboard, you _must_ configure it to cancel a customer's subscription if all retries for a payment fail.
1. In your Stripe dashboard, set up a product (with an optional statement descriptor), and set up a price for that product.
1. In the admin, create billing plans.
1. In the Stripe dashboard (live environment), the following webhooks should be set to point to `https://production.url/billing/stripe/webhook/`:

- TODO: fix for checkout vs api
- `invoice.paid`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `payment_method.automatically_updated`

## Usage

- The app should automatically create a Default Free plan during installation.
- To see relevant billing info in your admin, add `billing.admin.CustomerAdminInline` to your User admin `inlines`.
- `billing.serializers.CustomerSerializer` is available for returning Customer information. You can use it as a nested serializer in your User serializer.
  - E.g., `customer = billing.serializers.CustomerSerializer(read_only=True)`
- Users must have a first name, last name and email.
- Deleting a User or setting User.is_active to false will cancel any active Stripe subscriptions.
- Updating a User's first name, last name or email will update it on Stripe.

### Available API endpoints

- `/billing/create-subscription/`
- `/billing/cure-failed-card/`
- `/billing/cancel-subscription/`
- `/billing/reactivate-subscription/`
- `/billing/replace-card/`
- `/billing/stripe/webhook/`

### Conveniences

This package includes factories and serializers for use. Documentation to come!

### Usage Notes

- The app will assign a stripe `customer_id` to the `Customer` the first time the `User` requests to create a subscription. Before that, the `user.customer.customer_id` will be `null`.
- All paid plans must have a Stripe `price_id`.
- The app will automaticaly create a free_default plan the first time its needed if one doesn't exist and it will default to whatever defaults are specified in the Limits. You can modify the plan or even delete it, but there must always be 1 free_default plan and if there is not, the app will create it the next time it needs it.
- A user with a paid plan that has expired will drop to the limits set in the free_default plan. A user with a paid plan where there is no current_period_end set, which can happen if they have not completed the signup flow, will drop to the limits set in the free_default plan.
- A user with a free private (i.e. staff) plan that has expired will drop to the limits set in the free_default plan. A user with a free private plan where there
  is no current_period_end set will be treated as NO expiration date on the plan and will continue to enjoy the free private plan indefinitely.

## Development Stripe Notes

Generally, you won't need to use a real test environment `STRIPE_API_KEY` during local development. If `STRIPE_API_KEY=mock`, the application will be careful not to interface with Stripe and instead mock all of its responses.

But when testing, you may not want to use the `mock` sentinel since it may be difficult to introspect interactions with the Stripe library. Instead, you may just want to use `unittest.patch` like normal.

You can, of course, set the STRIPE_API_KEY variable to a real test environment key and it will interact with the Stripe testing environment. If you do this, you should create a RK by hand in the Stripe test environment console and use that.

## Deleting Test Data

From time to time, you may want to delete all Stripe test data via the dashboard. If you do that, your API keys should remain the same and won't need to be updated. But you will need to create a product and price in the Stripe dashboard and update any paid `Plan` instances to reflect the new `price_ids`.

## Possible Future Enhancements

- Multiple paid plans. Will need to write tests to upgrade/downgrade plans and those should be their own endpoints probably.
- Paid private plans, e.g., for grandfathering in pricing.
- Deal with payments that require additional action. see https://stripe.com/docs/billing/subscriptions/webhooks#action-required
- Customer payment history
- Verify Stripe webhook signatures
- Grace periods for expired payments
- Trial periods
  - Note to self: if this eventually does trials, `free_default` plans are still useful because they're what happens when the trial expires or a paid plan expires.
- Coupons for friends
- "When a subscription changes to past_due, your webhook script could email you about the problem so you can reach out to the customer, or the script could email the customer directly, asking them to update their payment details." Although maybe we could rely on this: https://stripe.com/docs/billing/subscriptions/overview#emails
- Inline admin of Stripe events for every User

## Architecture and Models

There are four models in this application: `Limit`, `Plan`, `PlanLimit`, and `Customer`.

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

`Plans` can be one of three types: `free_default`, `free_private`, and `paid`.

- There must at all times be exactly one `free_default Plan`. This is the plan that a user defaults to when they create an account. Or if their credit card doesn't go through. It's the 'fallback' plan when no other plan has been selected. If you have a free tier, it would be sensible to configure it as this plan. This plan must be free and does not interface with Stripe.
- A `free_private` plan is a plan that you can assign staff to have free access at a paid level or with some higher than normal limits.
- A `paid` plan must have a corresponding `price_id` in Stripe and is the only type of `Plan` that interfaces with Stripe.

N.B. I had considered making a `free_public` plan type that could be subscribed to. It was too difficult dealing with things like downgrading to a non-default free plan from a paid plan. You can't use the natural expiration of the paid plan without storing somewhere what free plan it will transition to. If this is ever something needed, we can think of the right way to build this.

**`free_default` versus `Limit` defaults**. A source of confusion can be what is the difference between the limit values configured in the `free_default Plan` and the defaults set on the `Limit` instances themselves? The `Limit` defaults attach when _any_ `Plan` does not define a value for _that particular `Limit`_. There has to be some value for a `Limit` in, say, a paid `Plan` even when that `Plan` does not specifically define the `Limit`.

The `free_default Plan` is simply another `Plan` that _may or may not_ define `Limits`. If it does not, then functionally there is no difference between the two since the plan will fall back to the defaults set on the `Limits`. If it does specifically define values for `Limits`, those values as defined become what a user falls back to when their credit card expires or they cancel their paid subscription.

Practically speaking, the real reason `Limits` have defaults is because there is no simple way to enforce that a `Plan` will have a many-to-many relationship with every single `Limit` defined in the database. If we could enforce that easily, there would be no need for defaults on the `Limit` instances themsleves.

There must always be one and only one `free_default Plan`. It's created in a data migration and this condition is enforced via a database constraint.

A `paid_public` plan is subscribable via the API. The others are not.

### Customer Model

For non-paid plans, the `Customer` model is pretty straightforward. The only attributes of real significance is the linked `Plan`, the `customer_id`, which is generated by Stripe for every User (paid or not), and `current_period_end`.

`current_period_end` is when the `Customer's` `Plan` will end if not renewed. After this time, the `Customer` falls back to the `free_default` Plan. If a `Customer`'s `Plan` is of type `free_default`, the `Customer` cannot have a `current_period_end` since that wouldn't make any sense, i.e., what would the `Customer` fall back to.

Every `User` must have a related `Customer`. The middleware will check this on every request and if the `User` does not have a `Customer`, it will create one.

For paid `Plans`, things are a little more complicated. Before we dive into it, first a brief primer on Stripe's subscription model.

#### Primer on Stripe's Subscription Model

Stripe's Subscription model can have a `status` of: `incomplete`, `incomplete_expired`, `active`, `past_due`, `canceled`, `trialing`, or `unpaid`.

`incomplete` means a Customer's credit card was attached to them and a subscription was created but the card was declined. The Customer has 23 hours to fix it and if they don't, the subscription gets `incomplete_expired` which is functionally the same as `canceled`. I.e., no invoices will be created or paid in those states.

`past_due` occurs when a recurring payment fails. The payment is retried according to settings in the Stripe dashboard. Once Stripe gives up, the status changes to `canceled`.

We don't use `trialing`, which is useful if you want to have trials where the customer puts in their credit card before the trial. We don't use `unpaid`, which is an alternative way of handling permanent recurring payment failures instead of making the status `cancelled`.

#### Back to Our Customer Model

There is a field on Customer called `payment_state` that is a function of the Stripe subscription state.

There is a property on Customer called `state` that is calculated from all the other attributes on Customer. These can be used for easy representation of Customer state on the frontend.

You can see what they are in `billing.models`. This can be improved and should probably operate more like a state machine.
