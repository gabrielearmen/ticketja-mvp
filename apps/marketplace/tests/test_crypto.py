from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings

from apps.marketplace.crypto import decrypt_secret, encrypt_secret


class MarketplaceTokenCryptoTests(SimpleTestCase):
    def test_encrypts_and_decrypts_without_exposing_plaintext(self):
        key = Fernet.generate_key().decode("ascii")

        with override_settings(
            MARKETPLACE_TOKEN_ENCRYPTION_KEYS=key,
        ):
            ciphertext = encrypt_secret("token-muito-secreto")
            plaintext = decrypt_secret(ciphertext)

        self.assertNotIn("token-muito-secreto", ciphertext)
        self.assertEqual(plaintext, "token-muito-secreto")

    def test_old_key_can_decrypt_during_rotation(self):
        old_key = Fernet.generate_key().decode("ascii")
        new_key = Fernet.generate_key().decode("ascii")

        with override_settings(
            MARKETPLACE_TOKEN_ENCRYPTION_KEYS=old_key,
        ):
            ciphertext = encrypt_secret("refresh-token")

        with override_settings(
            MARKETPLACE_TOKEN_ENCRYPTION_KEYS=(
                f"{new_key},{old_key}"
            ),
        ):
            plaintext = decrypt_secret(ciphertext)

        self.assertEqual(plaintext, "refresh-token")
