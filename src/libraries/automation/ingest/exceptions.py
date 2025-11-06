"""Exception types used by the ingest workflow."""


class FilenameValidationError(ValueError):
    """Raised when a filename does not match the expected convention."""


class ShotgridAuthenticationError(RuntimeError):
    """Raised when ShotGrid rejects the credentials used for ingest."""


class ShotgridSchemaError(RuntimeError):
    """Raised when ShotGrid rejects the payload due to schema mismatches."""


class ShotgridConnectivityError(RuntimeError):
    """Raised when ShotGrid cannot be reached after retries."""
