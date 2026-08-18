"""Provider-independent storage errors."""

class StorageError(Exception):
    """Base class for internal storage adapter errors."""

class ObjectNotFound(StorageError):
    """Requested object is missing."""

class InvalidReference(StorageError):
    """Storage reference is malformed or unsafe."""

class WriteFailure(StorageError):
    """Provider failed while writing bytes."""

class ReadFailure(StorageError):
    """Provider failed while reading bytes."""

class DeleteFailure(StorageError):
    """Provider failed while deleting bytes."""

class ProviderUnavailable(StorageError):
    """Provider cannot be used."""

class IntegrityMismatch(StorageError):
    """Actual bytes did not match expected integrity metadata."""

class ObjectAlreadyExists(StorageError):
    """Create-only write encountered different existing bytes."""
