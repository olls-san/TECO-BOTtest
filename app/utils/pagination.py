"""
utils/pagination.py
--------------------

Provides helpers for safely iterating through paginated API responses.

Tecopos and similar APIs may use page numbers or tokens to indicate
subsequent pages. ``paginate`` abstracts the control flow and
enforces sensible limits to avoid infinite loops or API misuse. The
function yields items from each page and stops when one of the
following conditions is met:

* A page returns an empty list of items.
* The next token is missing from the response.
* The next token is identical to the previous token.
* The configured maximum number of pages or items is reached.

Consumers can provide a callback to extract the list of items and the
next token from the raw JSON. A simple example using Tecopos page
numbering is included in the documentation.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional, Tuple, List
from app.core.config import get_settings


def paginate(
    fetch_page: Callable[[Any], dict],
    extract: Callable[[dict], Tuple[List[Any], Optional[Any]]],
    initial_token: Any = 1,
) -> List[Any]:
    """Iterate through pages of an API until termination criteria are met.

    :param fetch_page: function accepting a page token and returning the raw JSON
        response. The token may be an integer page number or an arbitrary
        token returned by the API.
    :param extract: function taking the raw JSON and returning a tuple of
        (items, next_token). ``items`` must be a list of entities to be
        accumulated. ``next_token`` is the token used to fetch the next
        page; ``None`` signals that no further pages exist.
    :param initial_token: starting token (defaults to page number ``1``)
    :return: a list containing all collected items across pages
    """
    settings = get_settings()
    items: List[Any] = []
    token = initial_token
    previous_token = None
    page_count = 0

    while True:
        page_count += 1
        if page_count > settings.max_pages:
            break
        response_json = fetch_page(token)
        page_items, next_token = extract(response_json)
        if not page_items:
            break
        items.extend(page_items)
        if len(items) >= settings.max_items:
            break
        # stop if next token is not present or repeats
        if next_token is None or next_token == previous_token:
            break
        previous_token = token
        token = next_token
    return items