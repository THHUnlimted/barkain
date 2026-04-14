"""M11 Billing — RevenueCat webhook + subscription status + tier resolution.

The iOS client is the authority for UI-level tier gating (it reads the
RevenueCat `customerInfoStream` directly). The backend uses
`users.subscription_tier` as the authority for rate limiting, kept in
sync via the `POST /api/v1/billing/webhook` endpoint that RevenueCat
hits on every subscription event.
"""
