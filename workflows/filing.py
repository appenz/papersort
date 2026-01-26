"""Filing workflow for processing and organizing documents."""

import os
import re
from datetime import date, datetime
from typing import Optional, Tuple

from papersort import PaperSort
from .docsorter import DocSorter
from .metadata_cache import compute_sha256
from .folder_matcher import resolve_company_folder


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


def copy_to_docstore(local_path: str, dest_path: str) -> bool:
    """Copy a file to the docstore."""
    try:
        PaperSort.docstore_driver.upload(local_path, dest_path)
        return True
    except Exception as e:
        PaperSort.print_right(f"Error copying file: {str(e)}")
        return False


def file_exists_in_docstore(dest_path: str) -> bool:
    """Check if a file exists in the docstore."""
    return PaperSort.docstore_driver.file_exists(dest_path)


def _move_in_docstore(old_path: str, new_path: str) -> bool:
    """Move a file within the docstore."""
    try:
        new_folder = os.path.dirname(new_path)
        PaperSort.docstore_driver.move(old_path, new_folder)
        return True
    except Exception as e:
        PaperSort.print_right(f"Error moving file: {str(e)}")
        return False


def process_file(pdf_path: str, cleanup_temp: bool = False,
                 source: Optional[str] = None, inbox_path: str = "") -> bool:
    """Process a single PDF file, using cache if available.
    
    Returns:
        True if file was successfully processed and copied (or already exists in docstore),
        False if processing failed or file couldn't be copied.
    """
    filename = os.path.basename(pdf_path)
    
    if os.path.getsize(pdf_path) == 0:
        PaperSort.print_right(f"Skipping empty file: {filename}")
        if cleanup_temp:
            os.unlink(pdf_path)
        return False
    
    file_hash = compute_sha256(pdf_path)
    existing = PaperSort.db.get_by_hash(file_hash)
    
    # Track metadata for copy logic
    title = None
    year = None
    suggested_path = None
    
    # --update: force re-evaluation via LLM, ignoring cached metadata
    if existing and not PaperSort.update:
        PaperSort.print_right(f"[yellow]Cached: {filename}[/yellow]")
        if existing.get('dest_path'):
            PaperSort.print_right(f"Current location: {existing['dest_path']}")
        PaperSort.print_right(f"File: {filename}")
        if existing.get('title'):
            PaperSort.print_right(f"Title: {existing['title']} {existing.get('year', '')}")
        if existing.get('entity'):
            PaperSort.print_right(f"Entity: {existing['entity']}")
        if existing.get('suggested_path'):
            conf = existing.get('confidence', 0) or 0
            PaperSort.print_right(f"Path ({conf * 10}%): {existing['suggested_path']}")
        if existing.get('summary'):
            preview = existing['summary'][:100] + ('...' if len(existing['summary']) > 100 else '')
            PaperSort.print_right(f"Summary: {preview}")
        
        title = existing.get('title')
        year = existing.get('year')
        suggested_path = existing.get('suggested_path')
    else:
        try:
            PaperSort.print_right(f"[red]Processing: {filename}[/red]")
            doc = DocSorter(pdf_path)
            if not doc.sort(llm_provider=PaperSort.llm_provider_name, inbox_path=inbox_path):
                if cleanup_temp:
                    os.unlink(pdf_path)
                return False
            doc.save_to_db(PaperSort.db, source=source)
            PaperSort.print_right(str(doc))
            
            title = doc.title
            year = doc.year
            suggested_path = doc.suggested_path
        except Exception as e:
            PaperSort.print_right(f"Error processing {filename}: {str(e)}")
            if cleanup_temp:
                os.unlink(pdf_path)
            return False
    
    if suggested_path:
        if DocSorter.path_exists(suggested_path):
            PaperSort.print_right(f"✓ Path '{suggested_path}' exists in layout")
        else:
            PaperSort.print_right(f"✗ Path '{suggested_path}' does not exist in layout")
        
        # Log to filing panel (left side) - shows what would be/was filed
        _log_filing(title, year, inbox_path, suggested_path)
    
    # Copy logic - track success for return value
    copy_success = False
    if PaperSort.copy and suggested_path and title and PaperSort.docstore_driver:
        copy_success = _handle_copy(
            pdf_path=pdf_path,
            file_hash=file_hash,
            title=title,
            year=year,
            suggested_path=suggested_path,
            existing=existing,
            inbox_path=inbox_path
        )
    
    if cleanup_temp:
        os.unlink(pdf_path)
    
    return copy_success


def _handle_copy(pdf_path: str, file_hash: str, title: str, 
                 year: Optional[int], suggested_path: str, 
                 existing: Optional[dict], inbox_path: str = "") -> bool:
    """Handle the copy logic for a processed file.
    
    Returns:
        True if file is successfully in docstore (copied, moved, or verified),
        False if copy/move failed.
    """
    # Resolve company folder names before copying
    layout_tree = DocSorter._get_layout()
    resolved_path = resolve_company_folder(suggested_path, layout_tree)
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
            if not PaperSort.verify:
                PaperSort.print_right("✓ Already in correct location (skipping)")
                return True  # Already copied successfully
            
            # Verify mode: check file actually exists
            if file_exists_in_docstore(current_dest_path):
                PaperSort.print_right(f"✓ Verified: {current_dest_path}")
                return True
            
            # File missing, re-copy to same location (no log - not a new file)
            PaperSort.print_right(f"! File missing at {current_dest_path}, re-copying...")
            if copy_to_docstore(pdf_path, current_dest_path):
                PaperSort.print_right(f"✓ Re-copied to: {current_dest_path}")
                return True
            return False
        
        # File is in wrong folder - needs to be moved (no log - not a new file)
        if current_dest_path:
            current_filename = os.path.basename(current_dest_path)
            new_dest_path = f"{suggested_path}/{current_filename}"
            
            PaperSort.print_right(f"Path changed: {current_folder} -> {suggested_path}")
            
            if file_exists_in_docstore(current_dest_path):
                # Move the file
                if _move_in_docstore(current_dest_path, new_dest_path):
                    PaperSort.db.update_copied(file_hash, new_dest_path)
                    PaperSort.print_right(f"✓ Moved to: {new_dest_path}")
                    return True
                else:
                    PaperSort.print_right("✗ Failed to move file")
                    return False
            else:
                # File missing at old location, copy to new location
                PaperSort.print_right("! File missing at old location, copying to new location...")
                if copy_to_docstore(pdf_path, new_dest_path):
                    PaperSort.db.update_copied(file_hash, new_dest_path)
                    PaperSort.print_right(f"✓ Copied to: {new_dest_path}")
                    return True
                return False
    
    # File not yet copied: copy to suggested path
    # This is a NEW file - eligible for --log
    base_dest = f"{suggested_path}/{base_name}"
    hash_dest = f"{suggested_path}/{hash_name}"
    
    # Try base name first (no hash suffix)
    if not file_exists_in_docstore(base_dest):
        if copy_to_docstore(pdf_path, base_dest):
            PaperSort.db.update_copied(file_hash, base_dest)
            PaperSort.print_right(f"✓ Copied to: {base_dest}")
            # Log if enabled (new file)
            if PaperSort.log:
                _copy_to_incoming_log(pdf_path, title, year, file_hash)
            return True
        return False
    
    # Base name exists - check if it's the same file (hash name exists)
    if file_exists_in_docstore(hash_dest):
        # File already there with hash suffix
        PaperSort.db.update_copied(file_hash, hash_dest)
        PaperSort.print_right(f"✓ Already exists: {hash_dest}")
        return True
    
    # Name collision with different file - use hash suffix
    if copy_to_docstore(pdf_path, hash_dest):
        PaperSort.db.update_copied(file_hash, hash_dest)
        PaperSort.print_right(f"✓ Copied to: {hash_dest}")
        # Log if enabled (new file)
        if PaperSort.log:
            _copy_to_incoming_log(pdf_path, title, year, file_hash)
        return True
    return False


def _log_filing(title: str, year: Optional[int], old_path: str, new_path: str) -> None:
    """Log a filing to the left panel."""
    timestamp = datetime.now().strftime("%H:%M")
    title_with_year = f"{title} {year}" if year else title
    # Extract just the directory from old_path (remove filename if present)
    old_dir = os.path.dirname(old_path) if '/' in old_path else old_path
    # If old_dir is empty (file was at root), use the original path
    if not old_dir:
        old_dir = old_path.split('/')[0] if '/' in old_path else old_path
    line1 = f"{timestamp} {title_with_year}"
    line2 = f"  {old_dir} → {new_path}"
    PaperSort.print_left(line1, line2)


def _copy_to_incoming_log(pdf_path: str, title: str, year: Optional[int],
                          file_hash: str) -> None:
    """Copy file to --IncomingLog folder with date-prefixed filename."""
    base_name, _ = generate_dest_filename(title, year, file_hash)
    date_prefix = date.today().strftime("%Y-%m-%d")
    log_filename = f"{date_prefix} {base_name}"
    log_dest = f"--IncomingLog/{log_filename}"
    
    if copy_to_docstore(pdf_path, log_dest):
        PaperSort.print_right(f"✓ Logged to: {log_dest}")


def process_local_inbox(inbox_path: str, delete_on_success: bool = False) -> None:
    """Process all PDFs in a local inbox directory recursively.
    
    Args:
        inbox_path: Path to the local inbox directory
        delete_on_success: If True, delete source files after successful copy
    """
    if not os.path.exists(inbox_path):
        PaperSort.print_right(f"Inbox directory '{inbox_path}' does not exist")
        return
    
    # First, collect all PDF files
    pdf_files = []
    for root, dirs, files in os.walk(inbox_path):
        for filename in files:
            if filename.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, filename))
    
    if not pdf_files:
        PaperSort.print_right("No PDF files found in inbox")
        return
    
    PaperSort.print_right(f"Found {len(pdf_files)} PDF files in inbox")
    PaperSort.set_total_files(len(pdf_files))
    
    # Process each file
    for i, filepath in enumerate(pdf_files, 1):
        PaperSort.set_progress(i, len(pdf_files))
        rel_path = os.path.relpath(filepath, inbox_path)
        PaperSort.print_right(f"\n--- {rel_path} ---")
        
        # Build source URI: local:{inbox_path}:{relative_path}
        source = f"local:{inbox_path}:{rel_path}"
        # Human-readable path: inbox folder name + relative path
        inbox_name = os.path.basename(inbox_path)
        readable_path = f"{inbox_name}/{rel_path}" if rel_path != os.path.basename(filepath) else inbox_name
        
        success = process_file(filepath, source=source, inbox_path=readable_path)
        
        # Delete source file after successful copy
        if delete_on_success and success:
            try:
                os.unlink(filepath)
                PaperSort.print_right(f"✓ Deleted from inbox: {rel_path}")
            except Exception as e:
                PaperSort.print_right(f"✗ Failed to delete from inbox: {e}")


def process_gdrive_inbox(inbox_folder_id: str, delete_on_success: bool = False) -> None:
    """Process all PDFs in a Google Drive inbox folder recursively.
    
    Args:
        inbox_folder_id: Google Drive folder ID for the inbox
        delete_on_success: If True, delete source files after successful copy
    """
    from storage import GDriveDriver, StorageError
    
    # Create GDrive driver for inbox
    inbox_driver = GDriveDriver(inbox_folder_id)
    
    # Get all PDFs recursively
    pdf_files = inbox_driver.list_files(recursive=True, extension=".pdf")
    
    if not pdf_files:
        PaperSort.print_right("No PDF files found in inbox")
        return
    
    PaperSort.print_right(f"Found {len(pdf_files)} PDF files in inbox")
    PaperSort.set_total_files(len(pdf_files))
    
    # Get human-readable inbox name
    inbox_name = inbox_driver._root_folder_name or "Inbox"
    
    for i, file_info in enumerate(pdf_files, 1):
        PaperSort.set_progress(i, len(pdf_files))
        PaperSort.print_right(f"\n--- {file_info.path} ---")
        
        # Build source URI: gdrive:{folder_id}:{path}
        source = f"gdrive:{inbox_folder_id}:{file_info.path}"
        # Human-readable path: inbox name + file path
        readable_path = f"{inbox_name}/{file_info.path}"
        
        # Download to temp file
        temp_path = inbox_driver.download_to_temp(file_info.path)
        
        try:
            # Process the file (cleanup_temp=True to delete after)
            success = process_file(temp_path, cleanup_temp=True, source=source, inbox_path=readable_path)
            
            # Delete source file after successful copy
            if delete_on_success and success:
                try:
                    inbox_driver.delete(file_info.path)
                    PaperSort.print_right(f"✓ Deleted from inbox: {file_info.path}")
                except StorageError as e:
                    PaperSort.print_right(f"✗ Failed to delete from inbox: {e}")
        except Exception as e:
            PaperSort.print_right(f"Error processing {file_info.name}: {str(e)}")
            # Ensure temp file is cleaned up even on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def process_dropbox_inbox(inbox_path: str, delete_on_success: bool = False) -> None:
    """Process all PDFs in a Dropbox inbox folder recursively.
    
    Args:
        inbox_path: Dropbox path for the inbox folder
        delete_on_success: If True, delete source files after successful copy
    """
    from storage import DropboxDriver, StorageError
    
    # Create Dropbox driver
    try:
        dbx = DropboxDriver(inbox_path)
    except StorageError as e:
        PaperSort.print_right(f"Error connecting to Dropbox: {str(e)}")
        return
    
    # Get all PDFs recursively
    try:
        pdf_files = dbx.list_files(recursive=True, extension=".pdf")
    except StorageError as e:
        PaperSort.print_right(f"Error listing Dropbox folder: {str(e)}")
        return
    
    if not pdf_files:
        PaperSort.print_right("No PDF files found in inbox")
        return
    
    PaperSort.print_right(f"Found {len(pdf_files)} PDF files in inbox")
    PaperSort.set_total_files(len(pdf_files))
    
    # Get human-readable inbox name from path
    inbox_name = os.path.basename(inbox_path.rstrip('/')) or "Inbox"
    
    for i, file_info in enumerate(pdf_files, 1):
        PaperSort.set_progress(i, len(pdf_files))
        PaperSort.print_right(f"\n--- {file_info.path} ---")
        
        # Build source URI: dropbox:{path}
        source = f"dropbox:{file_info.path}"
        # Human-readable path: inbox name + file path
        readable_path = f"{inbox_name}/{file_info.path}"
        
        # Download to temp file
        try:
            temp_path = dbx.download_to_temp(file_info.path)
        except StorageError as e:
            PaperSort.print_right(f"Error downloading {file_info.name}: {str(e)}")
            continue
        
        try:
            # Process the file (cleanup_temp=True to delete after)
            success = process_file(temp_path, cleanup_temp=True, source=source, inbox_path=readable_path)
            
            # Delete source file after successful copy
            if delete_on_success and success:
                try:
                    dbx.delete(file_info.path)
                    PaperSort.print_right(f"✓ Deleted from inbox: {file_info.path}")
                except StorageError as e:
                    PaperSort.print_right(f"✗ Failed to delete from inbox: {e}")
        except Exception as e:
            PaperSort.print_right(f"Error processing {file_info.name}: {str(e)}")
            # Ensure temp file is cleaned up even on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
