"""Domain errors for enrichment and external lookup failures."""


class EnrichmentNotFound(Exception):
    pass


class AlreadyClaimed(Exception):
    pass


class OpenalexUnavailable(Exception):
    pass


class RequestBudgetExceeded(Exception):
    pass
