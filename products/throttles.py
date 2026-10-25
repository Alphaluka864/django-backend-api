from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class RegistrationRateThrottle(AnonRateThrottle):
    scope = "registration"


class TokenRefreshRateThrottle(AnonRateThrottle):
    scope = "token_refresh"
