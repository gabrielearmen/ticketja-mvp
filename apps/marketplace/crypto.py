from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SecretDecryptionError(Exception):
    """Indica que um segredo persistido não pôde ser recuperado."""


def _configured_keys():
    raw_keys = getattr(
        settings,
        "MARKETPLACE_TOKEN_ENCRYPTION_KEYS",
        "",
    )

    keys = [
        item.strip()
        for item in str(raw_keys).split(",")
        if item.strip()
    ]

    if not keys:
        raise ImproperlyConfigured(
            "MARKETPLACE_TOKEN_ENCRYPTION_KEYS não foi configurada."
        )

    fernets = []

    for key in keys:
        try:
            fernets.append(Fernet(key.encode("ascii")))
        except (TypeError, ValueError) as error:
            raise ImproperlyConfigured(
                "MARKETPLACE_TOKEN_ENCRYPTION_KEYS contém uma chave "
                "Fernet inválida."
            ) from error

    return tuple(fernets)


def validate_encryption_configuration():
    _configured_keys()


def encrypt_secret(plaintext):
    normalized = str(plaintext or "").strip()

    if not normalized:
        raise ValueError("O segredo não pode estar vazio.")

    primary_fernet = _configured_keys()[0]
    return primary_fernet.encrypt(
        normalized.encode("utf-8")
    ).decode("ascii")


def decrypt_secret(ciphertext):
    normalized = str(ciphertext or "").strip()

    if not normalized:
        raise SecretDecryptionError(
            "O valor criptografado está vazio."
        )

    try:
        plaintext = MultiFernet(
            list(_configured_keys())
        ).decrypt(normalized.encode("ascii"))
    except (InvalidToken, UnicodeEncodeError) as error:
        raise SecretDecryptionError(
            "Não foi possível descriptografar o segredo."
        ) from error

    return plaintext.decode("utf-8")
