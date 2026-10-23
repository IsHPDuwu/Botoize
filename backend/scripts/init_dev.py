"""Create local development configuration without displaying secrets."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def main():
    target = Path(__file__).resolve().parents[1] / '.env'
    content = (
        '# Local development only. Do not commit or deploy this file.\n'
        'DJANGO_DEBUG=1\n'
        f'DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n'
        f'BOT_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n'
        'DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1\n'
    )
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('backend/.env already exists; left unchanged. Review it locally.')
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(content)
    print('Created backend/.env for local development; secrets were not displayed.')


if __name__ == '__main__':
    main()