from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.organizations.decorators import organizer_required
from apps.organizations.models import MembershipRole
from apps.organizations.selectors import ACTIVE_ORGANIZATION_SESSION_KEY

from .models import OrganizationPaymentAccount
from .oauth_client import OAuthClientError
from .services import (
    MarketplaceConnectionError,
    begin_mercado_pago_connection,
    complete_mercado_pago_connection,
)


@never_cache
@require_GET
@organizer_required
def payment_account_detail(request):
    account = OrganizationPaymentAccount.objects.filter(
        organization=request.active_organization
    ).first()

    context = {
        "organization": request.active_organization,
        "membership": request.organization_membership,
        "account": account,
        "can_manage": (
            request.organization_membership.role
            == MembershipRole.OWNER
        ),
        "oauth_enabled": settings.MARKETPLACE_OAUTH_ENABLED,
    }

    return render(
        request,
        "marketplace/payment_account_detail.html",
        context,
    )


@never_cache
@require_POST
@organizer_required
def mercado_pago_connect(request):
    try:
        authorization = begin_mercado_pago_connection(
            organization=request.active_organization,
            user=request.user,
        )
    except PermissionDenied:
        raise
    except ImproperlyConfigured:
        messages.error(
            request,
            "A conexão com o Mercado Pago ainda não está disponível.",
        )
        return redirect("marketplace:payment-account")

    return redirect(authorization.authorization_url)


@never_cache
@require_GET
@login_required
def mercado_pago_callback(request):
    if request.GET.get("error"):
        messages.error(
            request,
            "A autorização foi cancelada ou recusada no Mercado Pago.",
        )
        return redirect("organizations:dashboard")

    try:
        result = complete_mercado_pago_connection(
            state=request.GET.get("state"),
            code=request.GET.get("code"),
            user=request.user,
        )
    except PermissionDenied:
        raise
    except (MarketplaceConnectionError, OAuthClientError):
        messages.error(
            request,
            "Não foi possível concluir a conexão. Inicie uma nova autorização.",
        )
        return redirect("organizations:dashboard")
    except ImproperlyConfigured:
        messages.error(
            request,
            "A integração financeira ainda não está configurada.",
        )
        return redirect("organizations:dashboard")

    request.session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(
        result.account.organization_id
    )
    messages.success(
        request,
        "Conta Mercado Pago conectada com segurança.",
    )
    return redirect("marketplace:payment-account")
