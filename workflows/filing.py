"""Filing workflow for processing and organizing documents.

Handles:
- Processing PDFs from various inbox sources (local, Google Drive, Dropbox)
- Analyzing documents with LLM
- Copying/moving files to correct docstore locations
"""

import os
import re
from typing import Optional, Tuple, TYPE_CHECKING

from .docsorter import DocSorter
from .metadata_cache import MetadataCache, compute_sha256
from .folder_matcher import resolve_company_folder

if TYPE_CHECKING:
    from storage import StorageDriver


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename.
    
    Removes or replaces characters that are invalid in filenames.
    """
    # Replace problematic characters with safe alternatives
    name = name.replace('/', '-')
    name = name.replace('\\', '-')
    name = name.replace(':', '-')
    name = name.replace('*', '')
    name = name.replace('?', '')
    name = name.replace('"', "'")
    name = name.replace('<', '')
    name = name.replace('>', '')
    name = name.replace('|', '-')
    
    # Remove leading/trailing whitespace and dots
    name = name.strip().strip('.')
    
    # Collapse multiple spaces/dashes
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'-+', '-', name)
    
    # Limit length (leave room for hash suffix and extension)
    if len(name) > 100:
        name = name[:100].strip()
    
    return name


def generate_dest_filename(title: str, year: Optional[int], sha256: str, 
                          ext: str = ".pdf") -> Tuple[str, str]:
    """Generate base and collision-safe destination filenames.
    
    Args:
        title: Document title
        year: Document year (optional)
        sha256: SHA256 hash of the file
        ext: File extension (default: .pdf)
        
    Returns:
        Tuple of (base_name, hash_name) where:
        - base_name: "Title 2024.pdf"
        - hash_name: "Title 2024 [a1b2c3d4].pdf"
    """
    if year:
        base = sanitize_filename(f"{title} {year}")
    else:
        base = sanitize_filename(title)
    
    # Fallback if title is empty or sanitizes to nothing
    if not base:
        base = "Document"
    
    hash_prefix = sha256[:8]
    return (f"{base}{ext}", f"{base} [{hash_prefix}]{ext}")


def copy_to_docstore(local_path: str, dest_path: str, 
                     docstore_driver: "StorageDriver") -> bool:
    """Copy a file to the docstore.
    
    Args:
        local_path: Path to local file to copy
        dest_path: Destination path within docstore (folder/filename)
        docstore_driver: Storage driver for the docstore
        
    Returns:
        True if copy succeeded, False otherwise
    """
    try:
        docstore_driver.upload(local_path, dest_path)
        return True
    except Exception as e:
        print(f"Error copying file: {str(e)}")
        return False


def file_exists_in_docstore(dest_path: str, 
                            docstore_driver: "StorageDriver") -> bool:
    """Check if a file exists in the docstore.
    
    Args:
        dest_path: Path within docstore to check
        docstore_driver: Storage driver for the docstore
        
    Returns:
        True if file exists, False otherwise
    """
    return docstore_driver.file_exists(dest_path)


def _move_in_docstore(old_path: str, new_path: str, 
                      docstore_driver: "StorageDriver") -> bool:
    """Move a file within the docstore from old_path to new_path.
    
    Args:
        old_path: Current path within docstore
        new_path: New path within docstore
        docstore_driver: Storage driver for the docstore
        
    Returns:
        True if move succeeded, False otherwise
    """
    try:
        new_folder = os.path.dirname(new_path)
        docstore_driver.move(old_path, new_folder)
        return True
    except Exception as e:
        print(f"Error moving file: {str(e)}")
        return False


def process_file(pdf_path: str, db: MetadataCache, llm_provider: str,
                 update: bool = False, cleanup_temp: bool = False,
                 copy: bool = False, verify: bool = False, 
                 source: Optional[str] = None,
                 docstore_driver: Optional["StorageDriver"] = None) -> None:
    """Process a single PDF file, using cache if available.
    
    Args:
        pdf_path: Path to the PDF file (local path)
        db: MetadataCache database instance
        llm_provider: LLM provider to use
        update: If True, reprocess even if cached
        cleanup_temp: If True, delete the file after processing (for temp files)
        copy: If True, copy file to docstore after processing
        verify: If True, verify file exists at destination even if DB says copied
        source: Source URI for tracking (e.g., "gdrive:folder_id:path")
        docstore_driver: Storage driver for the docstore
    """
    filename = os.path.basename(pdf_path)
    
    if os.path.getsize(pdf_path) == 0:
        print(f"Skipping empty file: {filename}")
        if cleanup_temp:
            os.unlink(pdf_path)
        return
    
    file_hash = compute_sha256(pdf_path)
    existing = db.get_by_hash(file_hash)
    
    # Track metadata for copy logic
    title = None
    year = None
    suggested_path = None
    
    # --update: force re-evaluation via LLM, ignoring cached metadata
    if existing and not update:
        print(f"\033[93mCached: {filename}\033[0m")
        print(f"File: {filename}")
        if existing.get('title'):
            print(f"Title: {existing['title']} {existing.get('year', '')}")
        if existing.get('entity'):
            print(f"Entity: {existing['entity']}")
        if existing.get('suggested_path'):
            conf = existing.get('confidence', '')
            print(f"Path [{conf:2}]: {existing['suggested_path']}")
        if existing.get('summary'):
            preview = existing['summary'][:100] + ('...' if len(existing['summary']) > 100 else '')
            print(f"Summary: {preview}")
        
        title = existing.get('title')
        year = existing.get('year')
        suggested_path = existing.get('suggested_path')
    else:
        try:
            print(f"\033[91mProcessing: {filename}\033[0m")
            doc = DocSorter(pdf_path)
            if not doc.sort(llm_provider=llm_provider):
                if cleanup_temp:
                    os.unlink(pdf_path)
                return
            doc.save_to_db(db, source=source)
            print(doc)
            
            title = doc.title
            year = doc.year
            suggested_path = doc.suggested_path
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            if cleanup_temp:
                os.unlink(pdf_path)
            return
    
    if suggested_path:
        if DocSorter.path_exists(suggested_path):
            print(f"✓ Path '{suggested_path}' exists in layout")
        else:
            print(f"✗ Path '{suggested_path}' does not exist in layout")
    
    # Copy logic
    if copy and suggested_path and title and docstore_driver:
        _handle_copy(
            pdf_path=pdf_path,
            file_hash=file_hash,
            title=title,
            year=year,
            suggested_path=suggested_path,
            existing=existing,
            verify=verify,
            db=db,
            docstore_driver=docstore_driver,
            llm_provider=llm_provider
        )
    
    if cleanup_temp:
        os.unlink(pdf_path)


def _handle_copy(pdf_path: str, file_hash: str, title: str, 
                 year: Optional[int], suggested_path: str, existing: Optional[dict],
                 verify: bool, db: MetadataCache, 
                 docstore_driver: "StorageDriver",
                 llm_provider: str = "mistral") -> None:
    """Handle the copy logic for a processed file.
    
    Logic:
    1. Resolve company folder names to prevent duplicates (e.g., "JPMorgan" vs "J.P.Morgan")
    2. If file already copied to docstore:
       - If already in correct folder -> skip (or verify if --verify)
       - If in wrong folder -> move to correct folder
    3. If file not yet copied -> copy to suggested path
    """
    # Resolve company folder names before copying
    layout_tree = DocSorter._get_layout()
    resolved_path = resolve_company_folder(
        suggested_path,
        layout_tree,
        docstore_driver,
        llm_provider
    )
    if resolved_path != suggested_path:
        suggested_path = resolved_path
    
    # Generate the filename we'd use for this file
    base_name, hash_name = generate_dest_filename(title, year, file_hash)
    
    # Check if file was already copied (from DB)
    if existing and existing.get('copied'):
        current_dest_path = existing.get('dest_path')
        current_folder = os.path.dirname(current_dest_path) if current_dest_path else None
        
        # Compare current folder with suggested folder
        if current_folder == suggested_path:
            # File is already in the correct folder
            if not verify:
                print("✓ Already in correct location (skipping)")
                return
            
            # Verify mode: check file actually exists
            if file_exists_in_docstore(current_dest_path, docstore_driver):
                print(f"✓ Verified: {current_dest_path}")
                return
            
            # File missing, re-copy to same location
            print(f"! File missing at {current_dest_path}, re-copying...")
            if copy_to_docstore(pdf_path, current_dest_path, docstore_driver):
                print(f"✓ Re-copied to: {current_dest_path}")
            return
        
        # File is in wrong folder - needs to be moved
        if current_dest_path:
            current_filename = os.path.basename(current_dest_path)
            new_dest_path = f"{suggested_path}/{current_filename}"
            
            print(f"Path changed: {current_folder} -> {suggested_path}")
            
            if file_exists_in_docstore(current_dest_path, docstore_driver):
                # Move the file
                if _move_in_docstore(current_dest_path, new_dest_path, docstore_driver):
                    db.update_copied(file_hash, new_dest_path)
                    print(f"✓ Moved to: {new_dest_path}")
                else:
                    print("✗ Failed to move file")
            else:
                # File missing at old location, copy to new location
                print("! File missing at old location, copying to new location...")
                if copy_to_docstore(pdf_path, new_dest_path, docstore_driver):
                    db.update_copied(file_hash, new_dest_path)
                    print(f"✓ Copied to: {new_dest_path}")
            return
    
    # File not yet copied: copy to suggested path
    base_dest = f"{suggested_path}/{base_name}"
    hash_dest = f"{suggested_path}/{hash_name}"
    
    # Try base name first (no hash suffix)
    if not file_exists_in_docstore(base_dest, docstore_driver):
        if copy_to_docstore(pdf_path, base_dest, docstore_driver):
            db.update_copied(file_hash, base_dest)
            print(f"✓ Copied to: {base_dest}")
        return
    
    # Base name exists - check if it's the same file (hash name exists)
    if file_exists_in_docstore(hash_dest, docstore_driver):
        # File already there with hash suffix
        db.update_copied(file_hash, hash_dest)
        print(f"✓ Already exists: {hash_dest}")
        return
    
    # Name collision with different file - use hash suffix
    if copy_to_docstore(pdf_path, hash_dest, docstore_driver):
        db.update_copied(file_hash, hash_dest)
        print(f"✓ Copied to: {hash_dest}")


def process_local_inbox(inbox_path: str, db: MetadataCache, llm_provider: str,
                        update: bool = False, copy: bool = False, 
                        verify: bool = False,
                        docstore_driver: Optional["StorageDriver"] = None) -> None:
    """Process all PDFs in a local inbox directory recursively.
    
    Args:
        inbox_path: Local path to inbox directory
        db: MetadataCache database instance
        llm_provider: LLM provider to use
        update: If True, reprocess even if cached
        copy: If True, copy files to docstore
        verify: If True, verify files exist at destination
        docstore_driver: Storage driver for the docstore
    """
    if not os.path.exists(inbox_path):
        print(f"Inbox directory '{inbox_path}' does not exist")
        return
    
    # Use os.walk for recursive traversal
    for root, dirs, files in os.walk(inbox_path):
        for filename in files:
            if filename.lower().endswith('.pdf'):
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, inbox_path)
                print(f"\n--- {rel_path} ---")
                
                # Build source URI: local:{inbox_path}:{relative_path}
                source = f"local:{inbox_path}:{rel_path}"
                
                process_file(filepath, db, llm_provider, update=update,
                           copy=copy, verify=verify, source=source,
                           docstore_driver=docstore_driver)


def process_gdrive_inbox(inbox_folder_id: str, db: MetadataCache, 
                         llm_provider: str, update: bool = False, 
                         copy: bool = False, verify: bool = False,
                         docstore_driver: Optional["StorageDriver"] = None) -> None:
    """Process all PDFs in a Google Drive inbox folder recursively.
    
    Args:
        inbox_folder_id: Google Drive folder ID for inbox
        db: MetadataCache database instance
        llm_provider: LLM provider to use
        update: If True, reprocess even if cached
        copy: If True, copy files to docstore
        verify: If True, verify files exist at destination
        docstore_driver: Storage driver for the docstore
    """
    from storage import GDriveDriver
    
    # Create GDrive driver for inbox
    inbox_driver = GDriveDriver(inbox_folder_id)
    
    # Get all PDFs recursively
    pdf_files = inbox_driver.list_files(recursive=True, extension=".pdf")
    
    if not pdf_files:
        print("No PDF files found in inbox")
        return
    
    print(f"Found {len(pdf_files)} PDF files in inbox")
    
    for file_info in pdf_files:
        print(f"\n--- {file_info.path} ---")
        
        # Build source URI: gdrive:{folder_id}:{path}
        source = f"gdrive:{inbox_folder_id}:{file_info.path}"
        
        # Download to temp file
        temp_path = inbox_driver.download_to_temp(file_info.path)
        
        try:
            # Process the file (cleanup_temp=True to delete after)
            process_file(temp_path, db, llm_provider, update=update, 
                        cleanup_temp=True, copy=copy, verify=verify, 
                        source=source, docstore_driver=docstore_driver)
        except Exception as e:
            print(f"Error processing {file_info.name}: {str(e)}")
            # Ensure temp file is cleaned up even on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def process_dropbox_inbox(inbox_path: str, db: MetadataCache, 
                          llm_provider: str, update: bool = False,
                          copy: bool = False, verify: bool = False,
                          docstore_driver: Optional["StorageDriver"] = None) -> None:
    """Process all PDFs in a Dropbox inbox folder recursively.
    
    Args:
        inbox_path: Dropbox folder path (e.g., "/Inbox" or "/Documents/ToSort")
        db: MetadataCache database instance
        llm_provider: LLM provider to use
        update: If True, reprocess even if cached
        copy: If True, copy files to docstore
        verify: If True, verify files exist at destination
        docstore_driver: Storage driver for the docstore
    """
    from storage import DropboxDriver, StorageError
    
    # Create Dropbox driver
    try:
        dbx = DropboxDriver(inbox_path)
    except StorageError as e:
        print(f"Error connecting to Dropbox: {str(e)}")
        return
    
    # Get all PDFs recursively
    try:
        pdf_files = dbx.list_files(recursive=True, extension=".pdf")
    except StorageError as e:
        print(f"Error listing Dropbox folder: {str(e)}")
        return
    
    if not pdf_files:
        print("No PDF files found in inbox")
        return
    
    print(f"Found {len(pdf_files)} PDF files in inbox")
    
    for file_info in pdf_files:
        print(f"\n--- {file_info.path} ---")
        
        # Build source URI: dropbox:{path}
        source = f"dropbox:{file_info.path}"
        
        # Download to temp file
        try:
            temp_path = dbx.download_to_temp(file_info.path)
        except StorageError as e:
            print(f"Error downloading {file_info.name}: {str(e)}")
            continue
        
        try:
            # Process the file (cleanup_temp=True to delete after)
            process_file(temp_path, db, llm_provider, update=update,
                        cleanup_temp=True, copy=copy, verify=verify,
                        source=source, docstore_driver=docstore_driver)
        except Exception as e:
            print(f"Error processing {file_info.name}: {str(e)}")
            # Ensure temp file is cleaned up even on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
