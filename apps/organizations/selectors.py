from .models import OrganizationMembership, OrganizationStatus


ACTIVE_ORGANIZATION_SESSION_KEY = "active_organization_id"
REQUEST_MEMBERSHIP_CACHE = (
    "_ticketja_active_organization_membership"
)


def active_organizer_memberships_for(user):
    """
    Retorna vínculos ativos do usuário com organizações aprovadas.
    """
    if not user.is_authenticated:
        return OrganizationMembership.objects.none()

    return (
        OrganizationMembership.objects
        .select_related("organization")
        .filter(
            user=user,
            is_active=True,
            organization__status=OrganizationStatus.APPROVED,
        )
        .order_by("organization__name")
    )


def resolve_active_organizer_membership(request):
    """
    Resolve a organização ativa e armazena o resultado no request.

    O cache dura somente durante a requisição atual e evita que
    cabeçalho, dashboard e views repitam a mesma consulta.
    """
    if hasattr(request, REQUEST_MEMBERSHIP_CACHE):
        return getattr(
            request,
            REQUEST_MEMBERSHIP_CACHE,
        )

    memberships = active_organizer_memberships_for(request.user)

    organization_id = request.session.get(
        ACTIVE_ORGANIZATION_SESSION_KEY
    )

    membership = None

    if organization_id:
        membership = memberships.filter(
            organization_id=organization_id
        ).first()

    if membership is None:
        membership = memberships.first()

    if membership is None:
        request.session.pop(
            ACTIVE_ORGANIZATION_SESSION_KEY,
            None,
        )
    else:
        request.session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(
            membership.organization_id
        )

    setattr(
        request,
        REQUEST_MEMBERSHIP_CACHE,
        membership,
    )

    return membership