import os

os.environ['DJANGO_DEBUG'] = '1'
os.environ['DJANGO_SECRET_KEY'] = 'test-only-not-for-deployment-649c66822a26'
os.environ['BOT_ENCRYPTION_KEY'] = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='
from .settings import *  # noqa: F403

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']