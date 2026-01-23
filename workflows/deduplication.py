"""Deduplication workflow for merging duplicate company folders."""

from typing import List

from papersort import PaperSort
from storage import StorageError
from .docsorter import DocSorter
from models import create_llm


def list_subfolders(path: str) -> List[str]:
    """List subfolder names at a given path in the docstore."""
    try:
        folders = PaperSort.docstore_driver.list_folders(path)
        return [f.name for f in folders]
    except StorageError:
        return []


def list_files_in_folder(path: str) -> List[dict]:
    """List files in a folder."""
    try:
        files = PaperSort.docstore_driver.list_files(path)
        return [{'name': f.name, 'id': f.id} for f in files]
    except StorageError:
        return []


def merge_folders(source_folder: str, dest_folder: str, parent_path: str) -> bool:
    """Merge two folders by moving all files from source to destination."""
    source_path = f"{parent_path}/{source_folder}"
    dest_path = f"{parent_path}/{dest_folder}"
    
    try:
        # Get list of files in source folder
        files = list_files_in_folder(source_path)
        
        if not files:
            print(f"  No files to move from '{source_folder}'")
        else:
            print(f"  Moving {len(files)} file(s) from '{source_folder}' to '{dest_folder}'...")
        
        # Move each file
        for file_info in files:
            file_path = f"{source_path}/{file_info['name']}"
            PaperSort.docstore_driver.move(file_path, dest_path)
            print(f"    Moved: {file_info['name']}")
        
        # Delete the empty source folder
        PaperSort.docstore_driver.delete(source_path)
        print(f"  Deleted empty folder: {source_folder}")
        
        return True
        
    except Exception as e:
        print(f"  Error merging folders: {str(e)}")
        return False


def deduplicate_company_folders() -> None:
    """Find and merge duplicate company folders in the docstore."""
    # Get all paths that have 'By company' subfolders
    by_company_paths = DocSorter.get_by_company_paths()
    
    if not by_company_paths:
        print("No 'By company' folders found in layout")
        return
    
    print(f"Found {len(by_company_paths)} location(s) with company folders")
    
    total_merged = 0
    
    for parent_path in by_company_paths:
        print(f"\n=== Checking: {parent_path} ===")
        
        # Keep checking this folder until no more duplicates found
        while True:
            # Get current list of company subfolders
            subfolders = list_subfolders(parent_path)
            
            if len(subfolders) < 2:
                print(f"  Only {len(subfolders)} folder(s), skipping")
                break
            
            print(f"  Found {len(subfolders)} company folders")
            
            # Ask LLM to find a duplicate pair
            print("  Checking for duplicates...")
            llm = create_llm(PaperSort.llm_provider_name)
            duplicate_pair = llm.find_duplicate_pair(subfolders)
            
            if duplicate_pair is None:
                print("  No duplicates found")
                break
            
            folder1, folder2 = duplicate_pair
            
            # Count files in each folder to determine which to keep
            files1 = list_files_in_folder(f"{parent_path}/{folder1}")
            files2 = list_files_in_folder(f"{parent_path}/{folder2}")
            
            # Keep the folder with more files (or folder1 if equal)
            if len(files2) > len(files1):
                source, dest = folder1, folder2
                source_count, dest_count = len(files1), len(files2)
            else:
                source, dest = folder2, folder1
                source_count, dest_count = len(files2), len(files1)
            
            print("\n  Potential duplicate found:")
            print(f"    '{source}' ({source_count} files) -> '{dest}' ({dest_count} files)")
            
            # Ask for user confirmation
            response = input("  Merge these folders? [y/n]: ").strip().lower()
            
            if response == 'y':
                if merge_folders(source, dest, parent_path):
                    total_merged += 1
                    print("  Merged successfully!")
                else:
                    print("  Merge failed, skipping")
                    break
            else:
                print("  Skipped")
                # Continue checking for other duplicates (the skipped pair will
                # still be in the list, so we need to continue to next iteration
                # but the LLM might return the same pair. For now, we break.
                # A more sophisticated approach would track skipped pairs.
                break
    
    print("\n=== Deduplication complete ===")
    print(f"Total folders merged: {total_merged}")
