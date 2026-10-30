
"""
Django settings for config project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from datetime import timedelta


# --------------------------------------------------
# 1. Base directory and environment variables
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


# --------------------------------------------------
# 2. Security and development settings
# --------------------------------------------------

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError(
        "DJANGO_SECRET_KEY is missing. "
        "Add it to your .env file."
    )

DEBUG = os.getenv("DJANGO_DEBUG", "False").strip().lower() in {
    "true", "1", "yes", "on"
}

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]


# --------------------------------------------------
# 3. Installed applications
# --------------------------------------------------

INSTALLED_APPS = [
    # Django built-in applications
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party applications
    "rest_framework",
    "drf_spectacular",
    "django_filters",
    "rest_framework_simplejwt.token_blacklist",

    # Local applications
    "products",
]

# --------------------------------------------------
# 4. Middleware
# --------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# --------------------------------------------------
# 5. URL configuration
# --------------------------------------------------

ROOT_URLCONF = "config.urls"


# --------------------------------------------------
# 6. Template configuration
# --------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --------------------------------------------------
# 7. Application servers
# --------------------------------------------------

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# --------------------------------------------------
# 8. PostgreSQL database configuration
# --------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "shop_db"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

if not DATABASES["default"]["PASSWORD"]:
    raise RuntimeError(
        "DB_PASSWORD is missing. "
        "Add your PostgreSQL password to .env."
    )


# --------------------------------------------------
# 9. Django REST Framework configuration
# --------------------------------------------------


# --------------------------------------------------
# 9. Django REST Framework configuration
# --------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": (
        "rest_framework.pagination.PageNumberPagination"
    ),
    "PAGE_SIZE": 10,
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/minute",
        "registration": "3/hour",
        "token_refresh": "10/minute",
    },
}


SPECTACULAR_SETTINGS = {
    "TITLE": "Shop Backend API",
    "DESCRIPTION": (
        "API documentation for the Django shop backend, "
        "including products, inventory, suppliers, orders, "
        "seller management, and authentication."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
    "ENUM_NAME_OVERRIDES": {
        "ProductStatusEnum": [
            ("DRAFT", "Draft"),
            ("UNDER_REVIEW", "Under Review"),
            ("PUBLISHED", "Published"),
        ],
        "PurchaseOrderStatusEnum": [
            ("DRAFT", "Draft"),
            ("ORDERED", "Ordered"),
            ("RECEIVED", "Received"),
            ("CANCELLED", "Cancelled"),
        ],
        "SellerProfileStatusEnum": [
            ("PENDING", "Pending Approval"),
            ("APPROVED", "Approved"),
            ("REJECTED", "Rejected"),
            ("SUSPENDED", "Suspended"),
        ],
        "CustomerOrderStatusEnum": [
            ("PENDING", "Pending"),
            ("CONFIRMED", "Confirmed"),
            ("PROCESSING", "Processing"),
            ("SHIPPED", "Shipped"),
            ("DELIVERED", "Delivered"),
            ("CANCELLED", "Cancelled"),
        ],
    },
}



# --------------------------------------------------
# 9A. Environment-aware cache configuration
# --------------------------------------------------

DJANGO_CACHE_URL = os.getenv("DJANGO_CACHE_URL", "").strip()

if DJANGO_CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": DJANGO_CACHE_URL,
            "KEY_PREFIX": os.getenv(
                "DJANGO_CACHE_KEY_PREFIX",
                "shop_api",
            ),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": 2,
                "SOCKET_TIMEOUT": 2,
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": (
                "django.core.cache.backends.locmem.LocMemCache"
            ),
            "LOCATION": "shop-api-throttle-cache",
        }
    }


SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
}

# --------------------------------------------------
# 10. Password validation
# --------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# --------------------------------------------------
# 11. Internationalization
# --------------------------------------------------

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Africa/Dar_es_Salaam"

USE_I18N = True

USE_TZ = True


# --------------------------------------------------
# 12. Static files
# --------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# --------------------------------------------------
# 13. Default primary key
# --------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------
# 14. Security hardening
# --------------------------------------------------

# HTTPS enforcement is enabled through environment variables in production.
SECURE_SSL_REDIRECT = (
    os.getenv("DJANGO_SECURE_SSL_REDIRECT", "False").strip().lower()
    in {"true", "1", "yes", "on"}
)

SESSION_COOKIE_SECURE = (
    os.getenv("DJANGO_SESSION_COOKIE_SECURE", "False").strip().lower()
    in {"true", "1", "yes", "on"}
)

CSRF_COOKIE_SECURE = (
    os.getenv("DJANGO_CSRF_COOKIE_SECURE", "False").strip().lower()
    in {"true", "1", "yes", "on"}
)

SECURE_HSTS_SECONDS = int(
    os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0")
)

SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "False")
    .strip().lower() in {"true", "1", "yes", "on"}
)

SECURE_HSTS_PRELOAD = (
    os.getenv("DJANGO_SECURE_HSTS_PRELOAD", "False").strip().lower()
    in {"true", "1", "yes", "on"}
)

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
