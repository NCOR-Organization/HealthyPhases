class PublicationNotFound(LookupError):
    """A query, paper or request does not exist."""


class AcquisitionError(RuntimeError):
    """Remote content could not be retrieved or validated."""


class FullTextUnavailable(AcquisitionError):
    """No distributed PDF is available for this paper."""


class RequestAlreadyClaimed(RuntimeError):
    """Another run already owns this request."""
