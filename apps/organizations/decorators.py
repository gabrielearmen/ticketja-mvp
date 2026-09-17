from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .selectors import resolve_active_organizer_membership


def organizer_required(view_function):
    """
    Exige autenticação e vínculo ativo com uma organização aprovada.

    Quando autorizado, adiciona ao request:

    - request.organization_membership
    - request.active_organization
    """

    @wraps(view_function)
    def protected_view(request, *args, **kwargs):
        membership = resolve_active_organizer_membership(request)

        if membership is None:
            return render(
                request,
                "organizations/no_access.html",
                status=403,
            )

        request.organization_membership = membership
        request.active_organization = membership.organization

        return view_function(request, *args, **kwargs)

    return login_required(protected_view)