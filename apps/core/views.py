from django.shortcuts import render

from apps.events.selectors import (
    published_events_for_discovery,
)


def home(request):
    search_query = request.GET.get("q", "").strip()
    location_query = request.GET.get("local", "").strip()

    upcoming_events = published_events_for_discovery(
        search_query=search_query,
        location_query=location_query,
    )[:12]

    context = {
        "search_query": search_query,
        "location_query": location_query,
        "featured_events": (),
        "upcoming_events": upcoming_events,
    }

    return render(
        request,
        "core/home.html",
        context,
    )