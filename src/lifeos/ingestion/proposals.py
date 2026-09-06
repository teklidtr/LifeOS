"""Public ingestion proposal API with explicit composition.

The proposal models and lower-level builders live in ``_proposals_core``.  Cross-cutting
source/provenance, stable-target-identity, and prepublication behavior is composed through
ordinary functions in ``_proposal_composition``.  This facade preserves the existing public
imports without replacing its module object or rebinding the core module at import time.
"""

from lifeos.ingestion._proposal_composition import (
    build_compound_wiki_proposal,
    build_compounding_wiki_proposal,
    build_study_learning_proposal,
    build_wiki_section_update_proposal,
    persist_compound_wiki_proposal,
    persist_compounding_wiki_proposal,
    persist_study_learning_proposal,
    persist_wiki_section_update_proposal,
)
from lifeos.ingestion._proposals_core import *  # noqa: F403
from lifeos.ingestion._proposals_core import _persist_proposal_documents
