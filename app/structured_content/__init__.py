from .identity import *
from .enums import *
from .model import *
from .serialization import serialize_structured_content_candidate, to_canonical_dict
from .validation import *

_LAZY_REPOSITORY_EXPORTS = {
    "StructuredContentCandidateRepository": (".repository", "StructuredContentCandidateRepository"),
    "StructuredContentCandidateSummary": (".repository", "StructuredContentCandidateSummary"),
    "create_candidate": (".repository", "create_candidate"),
    "get_candidate": (".repository", "get_candidate"),
    "candidate_exists": (".repository", "candidate_exists"),
    "candidate_belongs_to_document": (".repository", "candidate_belongs_to_document"),
    "list_candidates_for_document": (".repository", "list_candidates_for_document"),
    "StructuredContentSelectionState": (".selection_types", "StructuredContentSelectionState"),
    "StructuredContentSelectionRepository": (".selection_repository", "StructuredContentSelectionRepository"),
    "StructuredContentSelectionService": (".selection_service", "StructuredContentSelectionService"),
}


def __getattr__(name: str):
    if name not in _LAZY_REPOSITORY_EXPORTS:
        raise AttributeError(name)
    from importlib import import_module

    module_name, export_name = _LAZY_REPOSITORY_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), export_name)
    globals()[name] = value
    return value


__all__ = [name for name in globals() if not name.startswith('_')] + list(_LAZY_REPOSITORY_EXPORTS)
