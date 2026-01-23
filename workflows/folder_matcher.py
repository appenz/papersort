"""Folder matching module for detecting similar company names."""

from typing import Dict, List, Optional

from papersort import PaperSort
from models import create_llm


def find_matching_company_folder(new_name: str, existing_folders: List[str]) -> Optional[str]:
    """Check if a new company folder name matches any existing folder."""
    if not existing_folders:
        return None
    
    # Check for exact match first (case-insensitive)
    for folder in existing_folders:
        if folder.lower() == new_name.lower():
            return folder
    
    llm = create_llm(PaperSort.llm_provider_name)
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


def get_existing_folders(parent_path: str) -> List[str]:
    """List existing subfolders in a parent path."""
    try:
        folders = PaperSort.docstore_driver.list_folders(parent_path)
        return [f.name for f in folders]
    except Exception as e:
        print(f"Warning: Could not list folders in '{parent_path}': {e}")
        return []


def gather_all_leaf_folders(top_level_path: str) -> Dict[str, str]:
    """Gather all leaf folders (filing destinations) under a top-level category."""
    folder_to_path: Dict[str, str] = {}
    
    def _traverse(current_path: str) -> None:
        try:
            subfolders = PaperSort.docstore_driver.list_folders(current_path)
        except Exception:
            return
        
        if not subfolders:
            folder_name = current_path.split('/')[-1] if '/' in current_path else current_path
            parent_path = '/'.join(current_path.split('/')[:-1])
            if folder_name and folder_name not in folder_to_path:
                folder_to_path[folder_name] = parent_path
            return
        
        for subfolder in subfolders:
            _traverse(f"{current_path}/{subfolder.name}")
    
    _traverse(top_level_path)
    return folder_to_path


def resolve_company_folder(suggested_path: str, layout_tree: Dict) -> str:
    """Resolve a suggested path, checking for similar company folder names."""
    if not is_by_company_path(suggested_path, layout_tree):
        return suggested_path
    
    parts = [p for p in suggested_path.split('/') if p]
    if len(parts) < 2:
        return suggested_path
    
    company_name = parts[-1]
    top_level = parts[0]
    
    folder_to_path = gather_all_leaf_folders(top_level)
    if not folder_to_path:
        return suggested_path
    
    all_folders = list(folder_to_path.keys())
    match = find_matching_company_folder(company_name, all_folders)
    
    if match and match != company_name:
        matched_parent = folder_to_path[match]
        new_path = f"{matched_parent}/{match}"
        print(f"Folder match: '{company_name}' -> '{match}' in '{matched_parent}'")
        return new_path
    
    return suggested_path
