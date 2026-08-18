from __future__ import annotations


class StructuredContentTransformationError(Exception):
    """Base bounded error for SPR to Structured Content transformation."""


class InvalidStructuredProcessingResult(StructuredContentTransformationError):
    def __init__(self, reason: str = "invalid structured processing result"):
        self.reason = reason
        super().__init__(reason)


class UnsupportedStructuredProcessingResultVersion(StructuredContentTransformationError):
    def __init__(self, *, schema_version: object, supported_schema_version: int):
        self.schema_version = schema_version
        self.supported_schema_version = supported_schema_version
        super().__init__(
            "unsupported structured processing result schema version: "
            f"{schema_version!r}; supported version is {supported_schema_version}"
        )


class MissingTransformationContext(StructuredContentTransformationError):
    def __init__(self):
        super().__init__("transformation context is required")


class InvalidTransformationContext(StructuredContentTransformationError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"invalid transformation context: {reason}")


class UnsupportedTransformationPolicyVersion(StructuredContentTransformationError):
    def __init__(self, *, policy_version: object, supported_policy_version: int):
        self.policy_version = policy_version
        self.supported_policy_version = supported_policy_version
        super().__init__(
            "unsupported transformation policy version: "
            f"{policy_version!r}; supported version is {supported_policy_version}"
        )


class UnsupportedMappingVersion(StructuredContentTransformationError):
    def __init__(self, *, mapping_version: object, supported_mapping_version: int):
        self.mapping_version = mapping_version
        self.supported_mapping_version = supported_mapping_version
        super().__init__(
            "unsupported structured content mapping version: "
            f"{mapping_version!r}; supported version is {supported_mapping_version}"
        )


class TransformationNotImplemented(StructuredContentTransformationError):
    def __init__(self, reason: str = "SPR mapping is outside M4 Slice 3B core page/text scope"):
        self.reason = reason
        super().__init__(reason)


class TransformationInvariantViolation(StructuredContentTransformationError):
    """Raised when contract-level transformer invariants are violated."""


class StructuredContentValidationFailed(TransformationInvariantViolation):
    def __init__(self, issue_count: int):
        self.issue_count = issue_count
        super().__init__(f"structured content validation failed with {issue_count} blocking issue(s)")
