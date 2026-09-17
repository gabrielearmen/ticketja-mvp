from django.contrib.auth.tokens import PasswordResetTokenGenerator


class AccountActivationTokenGenerator(PasswordResetTokenGenerator):
    """
    Gera tokens temporários para confirmação de e-mail.

    O estado ativo faz parte da assinatura. Depois da ativação,
    o token utilizado deixa de ser válido.
    """

    def _make_hash_value(self, user, timestamp):
        return (
            f"{user.pk}"
            f"{timestamp}"
            f"{user.is_active}"
            f"{user.email}"
        )


account_activation_token = AccountActivationTokenGenerator()