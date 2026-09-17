from django.shortcuts import render

from .decorators import organizer_required


@organizer_required
def organizer_dashboard(request):
    context = {
        "organization": request.active_organization,
        "membership": request.organization_membership,
    }

    return render(
        request,
        "organizations/dashboard.html",
        context,
    )