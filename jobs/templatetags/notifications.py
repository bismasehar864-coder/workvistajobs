"""The sidebar's unread badge.

An inclusion tag would be overkill for a number: this is a simple tag
returning an int, which the sidebar renders or omits. Either way it is
a tag rather than a context processor, so the query runs only on the
pages that show it - not on the public home page, the sign-in form, or
the employer dashboard, none of which have a badge.
"""

from django import template

from jobs.models import Notification


register = template.Library()


@register.simple_tag(takes_context=True)
def unread_notification_count(context):

    request = context.get("request")

    if request is None or not request.user.is_authenticated:
        return 0

    return Notification.objects.filter(
        user=request.user,
        read_at__isnull=True,
    ).count()
