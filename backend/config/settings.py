import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env', override=False)
DEBUG = os.environ.get('DJANGO_DEBUG', '0') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    raise ImproperlyConfigured('DJANGO_SECRET_KEY is required')
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
# Explicit operator proxy, restricted to QQ's official HTTP origin and Gateway.
QQ_HTTP_PROXY = os.environ.get('QQ_HTTP_PROXY', '') or None
QQ_GATEWAY_HOST = os.environ.get('QQ_GATEWAY_HOST', '') or None
# Owner-configured OneBot services commonly run on the same machine/LAN.
ONEBOT_UPSTREAM_ALLOW_PRIVATE = os.environ.get('ONEBOT_UPSTREAM_ALLOW_PRIVATE', '1' if DEBUG else '0') == '1'
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'rest_framework', 'core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'core.middleware.RequestIdMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware']
ROOT_URLCONF = 'config.urls'
AUTH_USER_MODEL = 'core.User'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
if os.environ.get('DB_ENGINE', 'sqlite') == 'postgres':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': os.environ['DB_NAME'], 'USER': os.environ['DB_USER'], 'PASSWORD': os.environ['DB_PASSWORD'], 'HOST': os.environ.get('DB_HOST', 'localhost'), 'PORT': os.environ.get('DB_PORT', '5432'), 'OPTIONS': {'sslmode': os.environ.get('DB_SSLMODE', 'require')}}}
elif not DEBUG:
    raise ImproperlyConfigured('Production requires DB_ENGINE=postgres')
BOT_ENCRYPTION_KEY = os.environ.get('BOT_ENCRYPTION_KEY', '')
from cryptography.fernet import Fernet
try:
    Fernet(BOT_ENCRYPTION_KEY.encode())
except (ValueError, TypeError) as exc:
    raise ImproperlyConfigured('BOT_ENCRYPTION_KEY must be a valid Fernet key') from exc
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_SAMESITE = 'Strict'
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
CSRF_TRUSTED_ORIGINS = [
    x for x in os.environ.get(
        'CSRF_TRUSTED_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173' if DEBUG else '',
    ).split(',') if x
]
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'EXCEPTION_HANDLER': 'core.throttle.exception_handler',
}
