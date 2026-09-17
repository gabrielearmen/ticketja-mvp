from .selectors import resolve_active_organizer_membership


def organizer_navigation(request):
    """
    Disponibiliza a organização ativa no cabeçalho de todas
    as páginas renderizadas.
    """
    if not request.user.is_authenticated:
        return {
            "navigation_organizer_membership": None,
        }

    return {
        "navigation_organizer_membership": (
            resolve_active_organizer_membership(request)
        ),
    }