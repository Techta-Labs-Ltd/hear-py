from __future__ import annotations
from src.resolver.models import SearchPlan
from src.utils.search_query import normalize_search_query

def build_hear_payload(plan: SearchPlan) -> dict:
    payload = {
        "alexaUserId": plan.alexa_user_id,
        "isLocal": plan.is_local,
        "isRecommended": plan.is_recommended,
        "limit": plan.limit,
        "page": plan.page,
        "query": normalize_search_query(plan.query),
    }
    if plan.sort != "relevance":
        payload["sort"] = plan.sort
    elif plan.is_local:
        payload["sort"] = "nearest"
    filters = {}
    if plan.is_publication:
        filters["isPublication"] = True
    for key, value in (
        ("categorySlugs", plan.category_slugs),
        ("tags", plan.tags),
        ("creatorIds", plan.creator_ids),
        ("organizationIds", plan.organization_ids),
        ("publicationIds", plan.publication_ids),
    ):
        if value:
            filters[key] = value
    if plan.city:
        filters["city"] = plan.city
    if plan.country_code:
        filters["countryCode"] = plan.country_code
    if plan.temporal:
        if plan.temporal.start_timestamp is not None:
            filters["publishedFrom"] = plan.temporal.start_timestamp
        if plan.temporal.end_timestamp is not None:
            filters["publishedTo"] = plan.temporal.end_timestamp
    if filters:
        payload["filter"] = filters
    return payload
