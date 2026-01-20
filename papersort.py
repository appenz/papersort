from docsorter.docsorter import DocSorter
from docsorter.docindex import DocIndex, compute_sha256
from docsorter.docllm import find_duplicate_pair
from gdrive.gdrive import GDrive, parse_storage_uri
import argparse
import os
import re
import shutil
from typing import List, Optional, Tuple

# Global GDrive instance for inbox operations (if using gdrive inbox)
_inbox_drive = None


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


def copy_to_docstore(local_path: str, dest_path: str, docstore_drive: Optional[GDrive], 
                     docstore_local_path: Optional[str]) -> bool:
    """Copy a file to the docstore.
    
    Args:
        local_path: Path to local file to copy
        dest_path: Destination path within docstore (folder/filename)
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        
    Returns:
        True if copy succeeded, False otherwise
    """
    try:
        if docstore_drive:
            # Upload to Google Drive
            docstore_drive.upload_file(local_path, dest_path)
        else:
            # Copy to local filesystem
            full_dest_path = os.path.join(docstore_local_path, dest_path)
            os.makedirs(os.path.dirname(full_dest_path), exist_ok=True)
            shutil.copy2(local_path, full_dest_path)
        return True
    except Exception as e:
        print(f"Error copying file: {str(e)}")
        return False


def file_exists_in_docstore(dest_path: str, docstore_drive: Optional[GDrive],
                            docstore_local_path: Optional[str]) -> bool:
    """Check if a file exists in the docstore.
    
    Args:
        dest_path: Path within docstore to check
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        
    Returns:
        True if file exists, False otherwise
    """
    if docstore_drive:
        return docstore_drive.file_exists(dest_path)
    else:
        full_path = os.path.join(docstore_local_path, dest_path)
        return os.path.exists(full_path)


def process_file(pdf_path, db, llm_provider, update=False, cleanup_temp=False,
                 copy=False, verify=False, source=None,
                 docstore_drive=None, docstore_local_path=None):
    """Process a single PDF file, using cache if available.
    
    Args:
        pdf_path: Path to the PDF file (local path)
        db: DocIndex database instance
        llm_provider: LLM provider to use
        update: If True, reprocess even if cached
        cleanup_temp: If True, delete the file after processing (for temp files)
        copy: If True, copy file to docstore after processing
        verify: If True, verify file exists at destination even if DB says copied
        source: Source URI for tracking (e.g., "gdrive:folder_id:path")
        docstore_drive: GDrive instance if docstore is on GDrive
        docstore_local_path: Local path if docstore is local
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
            
            if update and existing and existing.get('suggested_path') != suggested_path:
                print(f"\033[91mPath changed: {existing['suggested_path']} -> {suggested_path}\033[0m")
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
    if copy and suggested_path and title:
        _handle_copy(
            pdf_path=pdf_path,
            file_hash=file_hash,
            title=title,
            year=year,
            suggested_path=suggested_path,
            existing=existing,
            verify=verify,
            db=db,
            docstore_drive=docstore_drive,
            docstore_local_path=docstore_local_path
        )
    
    if cleanup_temp:
        os.unlink(pdf_path)


def _handle_copy(pdf_path, file_hash, title, year, suggested_path, existing,
                 verify, db, docstore_drive, docstore_local_path):
    """Handle the copy logic for a processed file.
    
    Copy flow:
    1. If copied=True in DB AND verify=False → skip (trust DB)
    2. If copied=True in DB AND verify=True → check dest_path exists, copy if missing
    3. For new files: check base name, then hash name for collision handling
    """
    # Check if already copied (from DB)
    if existing and existing.get('copied'):
        if not verify:
            # Trust DB, skip
            print(f"✓ Already copied (skipping)")
            return
        
        # Verify mode: check if dest_path actually exists
        dest_path = existing.get('dest_path')
        if dest_path and file_exists_in_docstore(dest_path, docstore_drive, docstore_local_path):
            print(f"✓ Verified: {dest_path}")
            return
        
        # File missing at dest_path, need to re-copy
        if dest_path:
            print(f"! File missing at {dest_path}, re-copying...")
            if copy_to_docstore(pdf_path, dest_path, docstore_drive, docstore_local_path):
                print(f"✓ Re-copied to: {dest_path}")
            return
    
    # New file or not yet copied: determine destination filename
    base_name, hash_name = generate_dest_filename(title, year, file_hash)
    
    # Build full destination paths
    base_dest = f"{suggested_path}/{base_name}"
    hash_dest = f"{suggested_path}/{hash_name}"
    
    # Check if base name exists
    if not file_exists_in_docstore(base_dest, docstore_drive, docstore_local_path):
        # No collision, use base name
        if copy_to_docstore(pdf_path, base_dest, docstore_drive, docstore_local_path):
            db.update_copied(file_hash, base_dest)
            print(f"✓ Copied to: {base_dest}")
        return
    
    # Base name exists (collision), check hash name
    if file_exists_in_docstore(hash_dest, docstore_drive, docstore_local_path):
        # Hash name also exists - file is already there
        db.update_copied(file_hash, hash_dest)
        print(f"✓ Already exists: {hash_dest}")
        return
    
    # Copy with hash-suffixed name
    if copy_to_docstore(pdf_path, hash_dest, docstore_drive, docstore_local_path):
        db.update_copied(file_hash, hash_dest)
        print(f"✓ Copied to: {hash_dest}")


def get_storage_display_name(uri):
    """Get a human-readable display name for a storage URI.
    
    Args:
        uri: Storage URI (e.g., 'gdrive:folder_id' or 'local:path')
        
    Returns:
        Tuple of (display_name, storage_type, value)
    """
    storage_type, value = parse_storage_uri(uri)
    
    if storage_type == "gdrive":
        # Query Google Drive for the folder name
        drive = GDrive(root_folder_id=value)
        folder_name = drive.root_folder['name']
        return (f"{folder_name} (Google Drive)", storage_type, value)
    elif storage_type == "local":
        # Use the path, or just the folder name for display
        return (f"{value} (local)", storage_type, value)
    else:
        return (uri, storage_type, value)


def load_layout(docstore_uri):
    """Load layout.txt from the docstore location.
    
    Args:
        docstore_uri: Storage URI (e.g., 'gdrive:folder_id' or 'local:path')
        
    Returns:
        Tuple of (GDrive instance or None, display_name)
    """
    storage_type, value = parse_storage_uri(docstore_uri)
    
    if storage_type == "gdrive":
        drive = GDrive(root_folder_id=value)
        layout_content = drive.read_file_content("layout.txt")
        DocSorter.set_layout_content(layout_content)
        display_name = f"{drive.root_folder['name']} (Google Drive)"
        return (drive, display_name)
    elif storage_type == "local":
        layout_path = os.path.join(value, "layout.txt")
        if not os.path.exists(layout_path):
            raise FileNotFoundError(f"Layout file not found: {layout_path}")
        with open(layout_path, 'r', encoding='utf-8') as f:
            layout_content = f.read()
        DocSorter.set_layout_content(layout_content)
        display_name = f"{value} (local)"
        return (None, display_name)
    else:
        raise ValueError(f"Unknown storage type: {storage_type}")


def process_local_inbox(inbox_path, db, llm_provider, copy=False, verify=False,
                        docstore_drive=None, docstore_local_path=None):
    """Process all PDFs in a local inbox directory recursively.
    
    Args:
        inbox_path: Local path to inbox directory
        db: DocIndex database instance
        llm_provider: LLM provider to use
        copy: If True, copy files to docstore
        verify: If True, verify files exist at destination
        docstore_drive: GDrive instance if docstore is on GDrive
        docstore_local_path: Local path if docstore is local
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
                
                process_file(filepath, db, llm_provider,
                           copy=copy, verify=verify, source=source,
                           docstore_drive=docstore_drive,
                           docstore_local_path=docstore_local_path)


def process_gdrive_inbox(inbox_folder_id, db, llm_provider, copy=False, verify=False,
                         docstore_drive=None, docstore_local_path=None):
    """Process all PDFs in a Google Drive inbox folder recursively.
    
    Args:
        inbox_folder_id: Google Drive folder ID for inbox
        db: DocIndex database instance
        llm_provider: LLM provider to use
        copy: If True, copy files to docstore
        verify: If True, verify files exist at destination
        docstore_drive: GDrive instance if docstore is on GDrive
        docstore_local_path: Local path if docstore is local
    """
    global _inbox_drive
    
    # Create GDrive instance for inbox
    _inbox_drive = GDrive(root_folder_id=inbox_folder_id)
    
    # Get all PDFs recursively
    pdf_files = _inbox_drive.list_files_recursive(extension=".pdf")
    
    if not pdf_files:
        print("No PDF files found in inbox")
        return
    
    print(f"Found {len(pdf_files)} PDF files in inbox")
    
    for file_info in pdf_files:
        print(f"\n--- {file_info['path']} ---")
        
        # Build source URI: gdrive:{folder_id}:{path}
        source = f"gdrive:{inbox_folder_id}:{file_info['path']}"
        
        # Download to temp file
        temp_path = _inbox_drive.download_to_temp(file_info['id'], file_info['name'])
        
        try:
            # Process the file (cleanup_temp=True to delete after)
            process_file(temp_path, db, llm_provider, cleanup_temp=True,
                        copy=copy, verify=verify, source=source,
                        docstore_drive=docstore_drive,
                        docstore_local_path=docstore_local_path)
        except Exception as e:
            print(f"Error processing {file_info['name']}: {str(e)}")
            # Ensure temp file is cleaned up even on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def main(copy=False, verify=False):
    """Main entry point for batch processing inbox.
    
    Args:
        copy: If True, copy files to docstore after processing
        verify: If True, verify files exist at destination
    """
    # Get configuration from environment
    docstore_uri = os.environ.get('DOCSTORE')
    inbox_uri = os.environ.get('INBOX')
    llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
    
    if not docstore_uri:
        print("Error: DOCSTORE environment variable not set")
        print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        return
    
    if not inbox_uri:
        print("Error: INBOX environment variable not set")
        print("Example: INBOX=gdrive:xyz789 or INBOX=local:inbox")
        return
    
    # Load layout from docstore and get drive instance
    docstore_drive, docstore_name = load_layout(docstore_uri)
    
    # Determine local path if docstore is local
    docstore_type, docstore_value = parse_storage_uri(docstore_uri)
    docstore_local_path = docstore_value if docstore_type == "local" else None
    
    # Get inbox display name
    inbox_name, inbox_type, inbox_value = get_storage_display_name(inbox_uri)
    
    print(f"Using LLM provider: {llm_provider}")
    print(f"Docstore: {docstore_name}")
    print(f"Inbox: {inbox_name}")
    if copy:
        print(f"Copy mode: enabled" + (" (with verify)" if verify else ""))
    
    # Initialize database
    db = DocIndex()
    
    # Process inbox based on type
    if inbox_type == "gdrive":
        process_gdrive_inbox(inbox_value, db, llm_provider,
                            copy=copy, verify=verify,
                            docstore_drive=docstore_drive,
                            docstore_local_path=docstore_local_path)
    elif inbox_type == "local":
        process_local_inbox(inbox_value, db, llm_provider,
                           copy=copy, verify=verify,
                           docstore_drive=docstore_drive,
                           docstore_local_path=docstore_local_path)
    else:
        print(f"Unknown inbox storage type: {inbox_type}")
    
    db.close()


def list_subfolders(path: str, docstore_drive: Optional[GDrive], 
                    docstore_local_path: Optional[str]) -> List[str]:
    """List subfolder names at a given path in the docstore.
    
    Args:
        path: Path within docstore to list
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        
    Returns:
        List of subfolder names (not full paths)
    """
    if docstore_drive:
        items = docstore_drive.list_items(path)
        # Filter to only folders
        return [item['name'] for item in items 
                if item.get('mimeType') == 'application/vnd.google-apps.folder']
    else:
        full_path = os.path.join(docstore_local_path, path)
        if not os.path.exists(full_path):
            return []
        return [name for name in os.listdir(full_path) 
                if os.path.isdir(os.path.join(full_path, name))]


def list_files_in_folder(path: str, docstore_drive: Optional[GDrive],
                         docstore_local_path: Optional[str]) -> List[dict]:
    """List files in a folder.
    
    Args:
        path: Path within docstore
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        
    Returns:
        List of dicts with 'name' key (and 'id' for GDrive)
    """
    if docstore_drive:
        items = docstore_drive.list_items(path)
        # Filter to only files (not folders)
        return [{'name': item['name'], 'id': item['id']} for item in items 
                if item.get('mimeType') != 'application/vnd.google-apps.folder']
    else:
        full_path = os.path.join(docstore_local_path, path)
        if not os.path.exists(full_path):
            return []
        return [{'name': name} for name in os.listdir(full_path) 
                if os.path.isfile(os.path.join(full_path, name))]


def merge_folders(source_folder: str, dest_folder: str, parent_path: str,
                  docstore_drive: Optional[GDrive], 
                  docstore_local_path: Optional[str]) -> bool:
    """Merge two folders by moving all files from source to destination.
    
    Moves all files from source_folder to dest_folder, then deletes the
    now-empty source_folder.
    
    Args:
        source_folder: Name of the source folder (to be emptied and deleted)
        dest_folder: Name of the destination folder (receives files)
        parent_path: Parent path containing both folders
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        
    Returns:
        True if merge succeeded, False otherwise
    """
    source_path = f"{parent_path}/{source_folder}"
    dest_path = f"{parent_path}/{dest_folder}"
    
    try:
        # Get list of files in source folder
        files = list_files_in_folder(source_path, docstore_drive, docstore_local_path)
        
        if not files:
            print(f"  No files to move from '{source_folder}'")
        else:
            print(f"  Moving {len(files)} file(s) from '{source_folder}' to '{dest_folder}'...")
        
        if docstore_drive:
            # Google Drive: use move_file for each file
            for file_info in files:
                file_path = f"{source_path}/{file_info['name']}"
                docstore_drive.move_file(file_path, dest_path)
                print(f"    Moved: {file_info['name']}")
            
            # Delete the empty source folder
            docstore_drive.delete_item(source_path)
            print(f"  Deleted empty folder: {source_folder}")
            
        else:
            # Local filesystem
            source_full = os.path.join(docstore_local_path, source_path)
            dest_full = os.path.join(docstore_local_path, dest_path)
            
            for file_info in files:
                src_file = os.path.join(source_full, file_info['name'])
                dst_file = os.path.join(dest_full, file_info['name'])
                
                # Handle potential name collision
                if os.path.exists(dst_file):
                    # Add a suffix to avoid overwriting
                    base, ext = os.path.splitext(file_info['name'])
                    counter = 1
                    while os.path.exists(dst_file):
                        dst_file = os.path.join(dest_full, f"{base}_{counter}{ext}")
                        counter += 1
                    print(f"    Moved (renamed): {file_info['name']} -> {os.path.basename(dst_file)}")
                else:
                    print(f"    Moved: {file_info['name']}")
                
                shutil.move(src_file, dst_file)
            
            # Remove the empty source folder
            os.rmdir(source_full)
            print(f"  Deleted empty folder: {source_folder}")
        
        return True
        
    except Exception as e:
        print(f"  Error merging folders: {str(e)}")
        return False


def deduplicate_company_folders(docstore_drive: Optional[GDrive],
                                docstore_local_path: Optional[str],
                                llm_provider: str) -> None:
    """Find and merge duplicate company folders in the docstore.
    
    Iterates through all 'By company' folder locations in the layout,
    uses LLM to detect potential duplicates, and merges them with user
    confirmation.
    
    Args:
        docstore_drive: GDrive instance if docstore is on GDrive, None otherwise
        docstore_local_path: Local path to docstore if local, None otherwise
        llm_provider: LLM provider to use ("mistral" or "openai")
    """
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
            subfolders = list_subfolders(parent_path, docstore_drive, docstore_local_path)
            
            if len(subfolders) < 2:
                print(f"  Only {len(subfolders)} folder(s), skipping")
                break
            
            print(f"  Found {len(subfolders)} company folders")
            
            # Ask LLM to find a duplicate pair
            print("  Checking for duplicates...")
            duplicate_pair = find_duplicate_pair(subfolders, llm_provider)
            
            if duplicate_pair is None:
                print("  No duplicates found")
                break
            
            folder1, folder2 = duplicate_pair
            
            # Count files in each folder to determine which to keep
            files1 = list_files_in_folder(f"{parent_path}/{folder1}", 
                                         docstore_drive, docstore_local_path)
            files2 = list_files_in_folder(f"{parent_path}/{folder2}", 
                                         docstore_drive, docstore_local_path)
            
            # Keep the folder with more files (or folder1 if equal)
            if len(files2) > len(files1):
                source, dest = folder1, folder2
                source_count, dest_count = len(files1), len(files2)
            else:
                source, dest = folder2, folder1
                source_count, dest_count = len(files2), len(files1)
            
            print(f"\n  Potential duplicate found:")
            print(f"    '{source}' ({source_count} files) -> '{dest}' ({dest_count} files)")
            
            # Ask for user confirmation
            response = input("  Merge these folders? [y/n]: ").strip().lower()
            
            if response == 'y':
                if merge_folders(source, dest, parent_path, 
                               docstore_drive, docstore_local_path):
                    total_merged += 1
                    print(f"  Merged successfully!")
                else:
                    print(f"  Merge failed, skipping")
                    break
            else:
                print("  Skipped")
                # Continue checking for other duplicates (the skipped pair will
                # still be in the list, so we need to continue to next iteration
                # but the LLM might return the same pair. For now, we break.
                # A more sophisticated approach would track skipped pairs.
                break
    
    print(f"\n=== Deduplication complete ===")
    print(f"Total folders merged: {total_merged}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Document sorting utility")
    parser.add_argument("--showlayout", action="store_true", help="Print the document store layout")
    parser.add_argument("--file", type=str, help="Process a single file and exit")
    parser.add_argument("--update", action="store_true", help="Skip cache, reprocess and compare paths")
    parser.add_argument("--copy", action="store_true", help="Copy files to docstore after processing")
    parser.add_argument("--verify", action="store_true", help="Verify files exist at destination (use with --copy)")
    parser.add_argument("--deduplicate", action="store_true", 
                       help="Find and merge duplicate company folders in the docstore")
    args = parser.parse_args()

    # Get docstore from environment
    docstore_uri = os.environ.get('DOCSTORE')
    
    if args.deduplicate:
        if not docstore_uri:
            print("Error: DOCSTORE environment variable not set")
            print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        else:
            docstore_drive, docstore_name = load_layout(docstore_uri)
            docstore_type, docstore_value = parse_storage_uri(docstore_uri)
            docstore_local_path = docstore_value if docstore_type == "local" else None
            
            llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
            
            print(f"Docstore: {docstore_name}")
            print(f"Using LLM provider: {llm_provider}")
            print("Starting deduplication...")
            
            deduplicate_company_folders(docstore_drive, docstore_local_path, llm_provider)
    elif args.showlayout:
        if not docstore_uri:
            print("Error: DOCSTORE environment variable not set")
            print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        else:
            _, docstore_name = load_layout(docstore_uri)
            print(f"Docstore: {docstore_name}")
            DocSorter.print_layout()
    elif args.file:
        if not docstore_uri:
            print("Error: DOCSTORE environment variable not set")
            print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        else:
            docstore_drive, docstore_name = load_layout(docstore_uri)
            docstore_type, docstore_value = parse_storage_uri(docstore_uri)
            docstore_local_path = docstore_value if docstore_type == "local" else None
            
            print(f"Docstore: {docstore_name}")
            if args.copy:
                print(f"Copy mode: enabled" + (" (with verify)" if args.verify else ""))
            
            db = DocIndex()
            llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
            
            # Build source URI for single file (local file)
            source = f"local::{os.path.abspath(args.file)}"
            
            process_file(args.file, db, llm_provider, update=args.update,
                        copy=args.copy, verify=args.verify, source=source,
                        docstore_drive=docstore_drive,
                        docstore_local_path=docstore_local_path)
            db.close()
    else:
        main(copy=args.copy, verify=args.verify)
