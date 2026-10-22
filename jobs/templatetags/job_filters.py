from django import template

register = template.Library()


@register.filter
def clean_location(value):
    """
    Some scraped sources repeat the same location fragment several
    times in one string (e.g. "Remote, Remote/Worldwide,
    Remote/Worldwide, Remote") because the source page itself renders
    it that way across multiple nested elements we scrape as one
    block. Collapse to each distinct fragment, in first-seen order.
    """

    if not value:
        return value

    seen = []

    for part in str(value).split(','):
        part = part.strip()

        if part and part not in seen:
            seen.append(part)

    return ', '.join(seen[:3])
