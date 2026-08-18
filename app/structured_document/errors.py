from __future__ import annotations


class StructuredDocumentError(Exception):
    """Base bounded error for Structured Document contracts."""


class StructuredDocumentAssemblyError(StructuredDocumentError):
    """Base bounded error for Structured Document assembly."""


class InvalidStructuredContentInput(StructuredDocumentAssemblyError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"invalid structured content input: {reason}")


class UnsupportedStructuredDocumentVersion(StructuredDocumentAssemblyError):
    def __init__(self, *, schema_version: object, supported_schema_version: int):
        self.schema_version = schema_version
        self.supported_schema_version = supported_schema_version
        super().__init__(
            "unsupported structured document schema version: "
            f"{schema_version!r}; supported version is {supported_schema_version}"
        )


class UnsupportedAssemblyPolicyVersion(StructuredDocumentAssemblyError):
    def __init__(self, *, policy_version: object, supported_policy_version: int):
        self.policy_version = policy_version
        self.supported_policy_version = supported_policy_version
        super().__init__(
            "unsupported structured document assembly policy version: "
            f"{policy_version!r}; supported version is {supported_policy_version}"
        )


class InvalidAssemblyPolicy(StructuredDocumentAssemblyError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"invalid structured document assembly policy: {reason}")


class StructuredDocumentAssemblyNotImplemented(StructuredDocumentAssemblyError):
    def __init__(self):
        super().__init__("structured document assembly is not implemented")


class StructuredDocumentAssemblyInvariantViolation(StructuredDocumentAssemblyError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"structured document assembly invariant violation: {reason}")


class StructuredDocumentValidationFailed(StructuredDocumentAssemblyError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"structured document validation failed: {reason}")
