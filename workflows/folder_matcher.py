"""
Folder matching module for detecting similar company names.

This module provides functionality to check if a new company folder name
matches any existing folders, preventing duplicates like "JPMorgan" vs "J.P.Morgan".
"""

from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from storage import StorageDriver


def find_matching_company_folder(
    new_name: str,
    existing_folders: List[str],
    llm_provider: str = "mistral"
) -> Optional[str]:
    """Check if a new company folder name matches any existing folder.
    
    Uses an LLM to intelligently compare the new name against ALL existing
    folders at once, handling variations like "JPMorgan" vs "J.P. Morgan".
    
    Args:
        new_name: The proposed new folder name
        existing_folders: List of existing folder names in the same directory
        llm_provider: LLM provider to use ("mistral" or "openai")
        
    Returns:
        The matching existing folder name if found, None otherwise
    """
    if not existing_folders:
        return None
    
    # Check for exact match first (case-insensitive)
    for folder in existing_folders:
        if folder.lower() == new_name.lower():
            return folder
    
    # Use the models layer - send all folders at once for better context
    from models import create_llm
    llm = create_llm(llm_provider)
    
    return llm.find_matching_folder(new_name, existing_folders)


def is_by_company_path(path: str, layout_tree: Dict) -> bool:
    """Check if the last segment of a path corresponds to a 'By company' folder in the layout.
    
    Args:
        path: The full path to check (e.g., "Financial & Banking/Bank Accounts/Chase")
        layout_tree: The parsed layout tree from DocSorter
        
    Returns:
        True if the parent folder in the layout has a 'By company' child
    """
    if not path:
        return False
    
    parts = [p for p in path.split('/') if p]
    if len(parts) < 2:
        return False
    
    # Navigate to the parent folder in the layout tree
    current = layout_tree
    for part in parts[:-1]:  # All parts except the last (company name)
        if part not in current:
            return False
        current = current[part]
    
    # Check if current level has "By company" as a child
    return any(key.lower() == "by company" for key in current.keys())


def get_existing_folders(
    parent_path: str,
    docstore_driver: "StorageDriver"
) -> List[str]:
    """List existing subfolders in a parent path.
    
    Args:
        parent_path: Path to the parent folder (e.g., "Financial & Banking/Bank Accounts")
        docstore_driver: Storage driver for the docstore
        
    Returns:
        List of subfolder names in the parent path
    """
    try:
        folders = docstore_driver.list_folders(parent_path)
        return [f.name for f in folders]
    except Exception as e:
        print(f"Warning: Could not list folders in '{parent_path}': {e}")
        return []


def gather_all_leaf_folders(
    top_level_path: str,
    docstore_driver: "StorageDriver"
) -> Dict[str, str]:
    """Gather all leaf folders (filing destinations) under a top-level category.
    
    Recursively traverses the docstore to find all leaf folders - these are
    folders that contain files but no subfolders, representing actual filing
    destinations like company folders.
    
    This captures both:
    - Dynamically-created folders from "By company" paths
    - Statically-defined folders in the layout
    
    Args:
        top_level_path: The top-level category to search under (e.g., "Financial & Banking")
        docstore_driver: Storage driver for the docstore
        
    Returns:
        Dict mapping folder name -> full parent path (e.g., {"Chase": "Financial/Banks"})
    """
    folder_to_path: Dict[str, str] = {}
    
    def _traverse(current_path: str) -> None:
        """Recursively find leaf folders."""
        try:
            subfolders = docstore_driver.list_folders(current_path)
        except Exception:
            return
        
        if not subfolders:
            # This is a leaf folder - add it
            # Extract just the folder name from the path
            folder_name = current_path.split('/')[-1] if '/' in current_path else current_path
            parent_path = '/'.join(current_path.split('/')[:-1])
            
            if folder_name and folder_name not in folder_to_path:
                folder_to_path[folder_name] = parent_path
            return
        
        # Has subfolders - recurse into each
        for subfolder in subfolders:
            subfolder_path = f"{current_path}/{subfolder.name}"
            _traverse(subfolder_path)
    
    _traverse(top_level_path)
    return folder_to_path


def resolve_company_folder(
    suggested_path: str,
    layout_tree: Dict,
    docstore_driver: "StorageDriver",
    llm_provider: str = "mistral"
) -> str:
    """Resolve a suggested path, checking for similar company folder names.
    
    If the path ends with a dynamically-created company folder (from 'By company'
    in the layout), this function checks if a similar folder already exists and
    returns the path with the existing folder name substituted.
    
    Enhanced behavior: Gathers ALL leaf folders under the same top-level category,
    including both dynamically-created folders (from "By company") and statically-
    defined folders in the layout. This ensures we don't miss potential matches.
    
    Args:
        suggested_path: The path suggested by the document sorter
        layout_tree: The parsed layout tree from DocSorter
        docstore_driver: Storage driver for the docstore
        llm_provider: LLM provider to use for matching
        
    Returns:
        The resolved path (possibly with substituted folder name and parent path)
    """
    # Check if this path ends with a "By company" folder
    if not is_by_company_path(suggested_path, layout_tree):
        return suggested_path
    
    parts = [p for p in suggested_path.split('/') if p]
    if len(parts) < 2:
        return suggested_path
    
    company_name = parts[-1]
    top_level = parts[0]
    
    # Gather all leaf folders under the top-level category
    # This includes both static layout folders and dynamic "By company" folders
    folder_to_path = gather_all_leaf_folders(top_level, docstore_driver)
    
    if not folder_to_path:
        return suggested_path
    
    # Check for match across all gathered folders
    all_folders = list(folder_to_path.keys())
    match = find_matching_company_folder(company_name, all_folders, llm_provider)
    
    if match and match != company_name:
        # Use the matched folder's actual parent path
        matched_parent = folder_to_path[match]
        new_path = f"{matched_parent}/{match}"
        print(f"Folder match: '{company_name}' -> '{match}' in '{matched_parent}'")
        return new_path
    
    return suggested_path
