from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import account_activation_token


def send_account_activation_email(*, user, request):
    """
    Envia o link de confirmação para a conta recém-criada.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = account_activation_token.make_token(user)

    activation_path = reverse(
        "accounts:activate",
        kwargs={
            "uidb64": uid,
            "token": token,
        },
    )

    activation_url = request.build_absolute_uri(activation_path)

    message = render_to_string(
        "accounts/emails/activation.txt",
        {
            "user": user,
            "activation_url": activation_url,
        },
    )

    send_mail(
        subject="Confirme seu e-mail no TicketJá",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )