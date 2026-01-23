"""Workflow layer for papersort.

Contains business logic for document processing workflows:
- Filing: Analyze and file documents from inboxes
- Deduplication: Merge duplicate company folders
- Document analysis: LLM-based metadata extraction
"""

from .docsorter import DocSorter
from .metadata_cache import MetadataCache, DocIndex, compute_sha256
from .folder_matcher import (
    find_matching_company_folder,
    resolve_company_folder,
    is_by_company_path,
    get_existing_folders,
)
from .filing import (
    sanitize_filename,
    generate_dest_filename,
    copy_to_docstore,
    file_exists_in_docstore,
    process_file,
    process_local_inbox,
    process_gdrive_inbox,
    process_dropbox_inbox,
)
from .deduplication import (
    list_subfolders,
    list_files_in_folder,
    merge_folders,
    deduplicate_company_folders,
)


__all__ = [
    # Document analysis
    'DocSorter',
    
    # Metadata cache
    'MetadataCache',
    'DocIndex',  # Backwards compatibility alias
    'compute_sha256',
    
    # Folder matching
    'find_matching_company_folder',
    'resolve_company_folder',
    'is_by_company_path',
    'get_existing_folders',
    
    # Filing workflow
    'sanitize_filename',
    'generate_dest_filename',
    'copy_to_docstore',
    'file_exists_in_docstore',
    'process_file',
    'process_local_inbox',
    'process_gdrive_inbox',
    'process_dropbox_inbox',
    
    # Deduplication workflow
    'list_subfolders',
    'list_files_in_folder',
    'merge_folders',
    'deduplicate_company_folders',
]
