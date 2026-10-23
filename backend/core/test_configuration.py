"""Configuration checks run outside pytest's test-only Django settings."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from cryptography.fernet import Fernet


BACKEND = Path(__file__).resolve().parents[1]


def isolated_environment():
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith(('DJANGO_', 'BOT_', 'DB_'))
        and key != 'PYTHON_DOTENV_DISABLED'
    }


def run_settings(tmp_path, values='', overrides=None):
    config = tmp_path / 'config'
    config.mkdir()
    shutil.copyfile(BACKEND / 'config/settings.py', config / 'settings.py')
    (tmp_path / '.env').write_text(values, encoding='utf-8')
    env = isolated_environment()
    env.update(overrides or {})
    return subprocess.run(
        [sys.executable, '-c', 'import runpy; runpy.run_path("config/settings.py")'],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )


def test_production_without_secret_rejected(tmp_path):
    result = run_settings(tmp_path)
    assert result.returncode != 0
    assert 'DJANGO_SECRET_KEY is required' in result.stderr


def test_development_dotenv_loads(tmp_path):
    result = run_settings(tmp_path, development_config())
    assert result.returncode == 0


def development_config():
    return (
        'DJANGO_DEBUG=1\nDJANGO_SECRET_KEY=configuration-test-only\n'
        f'BOT_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n'
    )


def test_exported_environment_overrides_dotenv(tmp_path):
    result = run_settings(tmp_path, development_config(), {'DJANGO_SECRET_KEY': ''})
    assert result.returncode != 0
    assert 'DJANGO_SECRET_KEY is required' in result.stderr


def test_production_still_requires_postgres(tmp_path):
    result = run_settings(tmp_path, development_config(), {'DJANGO_DEBUG': '0'})
    assert result.returncode != 0
    assert 'Production requires DB_ENGINE=postgres' in result.stderr


def test_development_initializer_does_not_overwrite_or_print_secrets(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    script = scripts / 'init_dev.py'
    shutil.copyfile(BACKEND / 'scripts/init_dev.py', script)
    first = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert first.returncode == 0
    original = (tmp_path / '.env').read_bytes()
    for line in original.decode().splitlines():
        if line.startswith(('DJANGO_SECRET_KEY=', 'BOT_ENCRYPTION_KEY=')):
            assert line.split('=', 1)[1] not in first.stdout + first.stderr
    second = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert second.returncode != 0
    assert (tmp_path / '.env').read_bytes() == original