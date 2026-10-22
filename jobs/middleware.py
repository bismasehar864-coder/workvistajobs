from urllib.parse import urlsplit

from django.conf import settings
from django.shortcuts import redirect


GUEST_ONLY_VIEW_NAMES = {
    "signin",
    "login",
    "signup",
    "signup_employee",
    "signup_employer",
    "password_reset",
    "password_reset_done",
    "password_reset_confirm",
    "password_reset_complete",
}

PUBLIC_VIEW_NAMES = GUEST_ONLY_VIEW_NAMES | {
    "home",
    "job_detail",
    "search_jobs",
    "trending_jobs",
    "alerts_unsubscribe",
}
NO_STORE_VIEW_NAMES = {"logout"}


def _asset_prefix(url):
    path = urlsplit(url).path
    return "/" + path.lstrip("/") if path else ""


class NoCacheAuthenticatedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        view_name = getattr(request.resolver_match, "url_name", None)
        if request.user.is_authenticated and view_name in GUEST_ONLY_VIEW_NAMES:
            return redirect("dashboard")

        return None

    def __call__(self, request):
        response = self.get_response(request)
        view_name = getattr(request.resolver_match, "url_name", None)

        asset_prefixes = (
            _asset_prefix(settings.STATIC_URL),
            _asset_prefix(settings.MEDIA_URL),
        )
        is_asset = any(
            prefix != "/" and request.path.startswith(prefix)
            for prefix in asset_prefixes
        )
        authenticated_page = (
            request.user.is_authenticated
            and view_name not in PUBLIC_VIEW_NAMES
        )

        if not is_asset and (
            authenticated_page or view_name in NO_STORE_VIEW_NAMES
        ):
            response["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"

        return response

class NoStoreMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not request.path.startswith(("/static/", "/media/")):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"

        return response