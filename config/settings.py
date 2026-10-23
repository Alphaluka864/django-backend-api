
"""
Django settings for config project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


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

DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"

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

    # Local applications
    "products",
    'django_filters',
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

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
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


# --------------------------------------------------
# 13. Default primary key
# --------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
