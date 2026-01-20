"""
Folder matching module for detecting similar company names.

This module provides functionality to check if a new company folder name
matches any existing folders, preventing duplicates like "JPMorgan" vs "J.P.Morgan".
"""

import os
from typing import Dict, List, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from gdrive.gdrive import GDrive


# Prompt template for the LLM to compare company names
FOLDER_MATCH_PROMPT = """You are a helpful assistant that identifies if two company or organization names refer to the same entity.

I want to create a new folder named: "{new_name}"

Here are the existing folders in the same directory:
{existing_folders}

Does any existing folder refer to the same company/organization as the new folder name?

Consider that:
- Different capitalizations (e.g., "Chase" vs "CHASE") are the same
- Abbreviations vs full names (e.g., "JP Morgan" vs "JPMorgan Chase") are the same
- Minor punctuation differences (e.g., "J.P. Morgan" vs "JP Morgan") are the same
- Parent/subsidiary relationships where the name is essentially the same are matches

Respond with EXACTLY one of these formats:
- If there is a match: MATCH: <exact existing folder name>
- If there is no match: NO_MATCH

Do not include any other text in your response.
"""


def find_matching_company_folder(
    new_name: str,
    existing_folders: List[str],
    llm_provider: str = "mistral"
) -> Optional[str]:
    """Check if a new company folder name matches any existing folder.
    
    Uses an LLM to intelligently compare company names, handling variations
    like "JPMorgan" vs "J.P. Morgan" vs "JP Morgan Chase".
    
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
    
    # Format existing folders as a numbered list
    folders_list = "\n".join(f"- {folder}" for folder in existing_folders)
    
    prompt = FOLDER_MATCH_PROMPT.format(
        new_name=new_name,
        existing_folders=folders_list
    )
    
    # Get LLM response
    response = _call_llm(prompt, llm_provider)
    
    # Parse response
    return _parse_match_response(response, existing_folders)


def _call_llm(prompt: str, llm_provider: str) -> str:
    """Call the LLM with a simple text prompt.
    
    Args:
        prompt: The prompt text to send
        llm_provider: LLM provider to use ("mistral" or "openai")
        
    Returns:
        The LLM's response text
    """
    if llm_provider == "openai":
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    else:
        # Default to Mistral
        from mistralai import Mistral
        api_key = os.environ["MISTRAL_API_KEY"]
        client = Mistral(api_key=api_key)
        response = client.chat.complete(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content


def _parse_match_response(response: str, existing_folders: List[str]) -> Optional[str]:
    """Parse the LLM response to extract the matching folder name.
    
    Args:
        response: The raw LLM response text
        existing_folders: List of existing folder names to validate against
        
    Returns:
        The matching folder name if found and valid, None otherwise
    """
    response = response.strip()
    
    if response.upper() == "NO_MATCH":
        return None
    
    if response.upper().startswith("MATCH:"):
        match_name = response[6:].strip()
        
        # Validate that the match is actually in our list
        for folder in existing_folders:
            if folder.lower() == match_name.lower():
                return folder  # Return the exact casing from our list
        
        # If LLM returned a name not in our list, treat as no match
        print(f"Warning: LLM returned '{match_name}' which is not in existing folders")
        return None
    
    # Unexpected format - try to extract a folder name anyway
    for folder in existing_folders:
        if folder.lower() in response.lower():
            return folder
    
    return None


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
    docstore_drive: Optional["GDrive"],
    docstore_local_path: Optional[str]
) -> List[str]:
    """List existing subfolders in a parent path.
    
    Works with both Google Drive and local filesystem.
    
    Args:
        parent_path: Path to the parent folder (e.g., "Financial & Banking/Bank Accounts")
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        
    Returns:
        List of subfolder names in the parent path
    """
    folders = []
    
    try:
        if docstore_drive:
            # Use Google Drive API
            items = docstore_drive.list_items(parent_path)
            folders = [
                item['name'] for item in items
                if item.get('mimeType') == 'application/vnd.google-apps.folder'
            ]
        elif docstore_local_path:
            # Use local filesystem
            full_path = os.path.join(docstore_local_path, parent_path)
            if os.path.exists(full_path) and os.path.isdir(full_path):
                folders = [
                    name for name in os.listdir(full_path)
                    if os.path.isdir(os.path.join(full_path, name))
                ]
    except Exception as e:
        print(f"Warning: Could not list folders in '{parent_path}': {e}")
    
    return folders


def resolve_company_folder(
    suggested_path: str,
    layout_tree: Dict,
    docstore_drive: Optional["GDrive"],
    docstore_local_path: Optional[str],
    llm_provider: str = "mistral"
) -> str:
    """Resolve a suggested path, checking for similar company folder names.
    
    If the path ends with a dynamically-created company folder (from 'By company'
    in the layout), this function checks if a similar folder already exists and
    returns the path with the existing folder name substituted.
    
    Args:
        suggested_path: The path suggested by the document sorter
        layout_tree: The parsed layout tree from DocSorter
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        llm_provider: LLM provider to use for matching
        
    Returns:
        The resolved path (possibly with substituted folder name)
    """
    # Check if this path ends with a "By company" folder
    if not is_by_company_path(suggested_path, layout_tree):
        return suggested_path
    
    parts = [p for p in suggested_path.split('/') if p]
    company_name = parts[-1]
    parent_path = '/'.join(parts[:-1])
    
    # Get existing folders in the parent directory
    existing_folders = get_existing_folders(
        parent_path, docstore_drive, docstore_local_path
    )
    
    if not existing_folders:
        return suggested_path
    
    # Check if there's a matching folder
    match = find_matching_company_folder(company_name, existing_folders, llm_provider)
    
    if match and match != company_name:
        new_path = f"{parent_path}/{match}"
        print(f"Folder match: '{company_name}' -> '{match}'")
        return new_path
    
    return suggested_path
