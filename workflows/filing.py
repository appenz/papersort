"""Filing workflow for processing and organizing documents."""

import os
import re
from datetime import date, datetime
from typing import Optional, Tuple

from papersort import PaperSort
from .docsorter import DocSorter
from .file_metadata import FileMetadata
from .metadata_cache import compute_sha256
from .folder_matcher import resolve_company_folder
from . import ingress_log


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    name = name.replace('/', '-')
    name = name.replace('\\', '-')
    name = name.replace(':', '-')
    name = name.replace('*', '')
    name = name.replace('?', '')
    name = name.replace('"', "'")
    name = name.replace('<', '')
    name = name.replace('>', '')
    name = name.replace('|', '-')
    name = name.strip().strip('.')
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'-+', '-', name)
    if len(name) > 100:
        name = name[:100].strip()
    return name


def generate_dest_filename(title: str, year: Optional[int], sha256: str, 
                          ext: str = ".pdf") -> Tuple[str, str]:
    """Generate base and collision-safe destination filenames.
    
    Returns:
        Tuple of (base_name, hash_name) where:
        - base_name: "Title 2024.pdf"
        - hash_name: "Title 2024 [a1b2c3d4].pdf"
    """
    if year:
        base = sanitize_filename(f"{title} {year}")
    else:
        base = sanitize_filename(title)
    
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


def _get_docstore_uri(path: str) -> str:
    """Construct full URI for a path in the docstore."""
    driver = PaperSort.docstore_driver
    driver_type = type(driver).__name__
    
    if driver_type == "GDriveDriver":
        return f"gdrive:{driver.root_folder_id}:{path}"
    elif driver_type == "LocalDriver":
        return f"local:{driver.root_path}:{path}"
    elif driver_type == "DropboxDriver":
        return f"dropbox:{driver.root_path}:{path}"
    else:
        return f"unknown::{path}"


def _get_docstore_display_name() -> str:
    """Get human-readable name for the docstore."""
    return getattr(PaperSort.docstore_driver, 'display_name', 'Docstore')


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
    
    Args:
        pdf_path: Path to the local PDF file
        cleanup_temp: If True, delete the file after processing
        source: Source URI (e.g., "gdrive:folder_id:path/file.pdf")
        inbox_path: Human-readable inbox path for display
    
    Returns:
        True if file was successfully processed and copied (or already exists),
        False if processing failed or file couldn't be copied.
    """
    filename = os.path.basename(pdf_path)
    file_size = os.path.getsize(pdf_path)
    
    if file_size == 0:
        PaperSort.print_right(f"Skipping empty file: {filename}")
        ingress_log.log("ERROR", inbox_path or filename, None, filename, "Empty file")
        if cleanup_temp:
            os.unlink(pdf_path)
        return False
    
    # 1. Create source metadata
    file_hash = compute_sha256(pdf_path)
    src = FileMetadata(
        sha256=file_hash,
        original_filename=filename,
        file_size=file_size,
        src_uri=source,
        src_uri_display=inbox_path,
    )
    
    # 2. Cache lookup
    cached = PaperSort.db.get_by_hash(file_hash)
    
    # 3. Use cached or run analysis
    if cached and not PaperSort.update:
        cached.display_cached(PaperSort.print_right)
        meta = src.merge(cached)
    else:
        # Run LLM analysis
        PaperSort.print_right(f"[red]Processing: {filename}[/red]")
        try:
            extracted = DocSorter.analyze(
                pdf_path,
                llm_provider=PaperSort.llm_provider_name,
                inbox_path=inbox_path
            )
            if not extracted:
                ingress_log.log("ERROR", inbox_path or filename, None, filename, "Analysis failed")
                if cleanup_temp:
                    os.unlink(pdf_path)
                return False
            meta = src.merge(extracted)
            meta.display(PaperSort.print_right)
        except Exception as e:
            PaperSort.print_right(f"Error processing {filename}: {str(e)}")
            ingress_log.log("ERROR", inbox_path or filename, None, filename, str(e))
            if cleanup_temp:
                os.unlink(pdf_path)
            return False
    
    # 4. Validate suggested path
    if meta.suggested_path:
        if DocSorter.path_exists(meta.suggested_path):
            PaperSort.print_right(f"✓ Path '{meta.suggested_path}' exists in layout")
        else:
            PaperSort.print_right(f"✗ Path '{meta.suggested_path}' does not exist in layout")
        
        # Log to filing panel
        _log_filing(meta.title, meta.reporting_year, inbox_path, meta.suggested_path)
    
    # 5. Save to cache (always, even without --copy)
    PaperSort.db.save(meta)
    
    # 6. Copy if enabled
    copy_success = False
    if PaperSort.copy and meta.suggested_path and meta.title and PaperSort.docstore_driver:
        copy_success = _handle_copy(pdf_path, meta, cached)
    
    if cleanup_temp:
        os.unlink(pdf_path)
    
    return copy_success


def _handle_copy(pdf_path: str, meta: FileMetadata, 
                 cached: Optional[FileMetadata]) -> bool:
    """Handle the copy logic for a processed file.
    
    Returns:
        True if file is successfully in docstore (copied, moved, or verified),
        False if copy/move failed.
    """
    source = meta.src_uri_display or os.path.basename(pdf_path)
    summary = f"{meta.title} {meta.reporting_year}" if meta.reporting_year else meta.title
    
    # Resolve company folder names
    layout_tree = DocSorter._get_layout()
    resolved_path = resolve_company_folder(meta.suggested_path, layout_tree)
    
    # Generate filename
    base_name, hash_name = generate_dest_filename(
        meta.title, meta.reporting_year, meta.sha256
    )
    
    docstore_display = _get_docstore_display_name()
    
    # Check if file was already copied
    if cached and cached.copied and cached.dst_uri:
        # Extract path from dst_uri
        parts = cached.dst_uri.split(":", 2)
        current_dest_path = parts[2] if len(parts) == 3 else cached.dst_uri
        current_folder = os.path.dirname(current_dest_path)
        
        if current_folder == resolved_path:
            # File is in correct folder
            if not PaperSort.verify:
                PaperSort.print_right("✓ Already in correct location (skipping)")
                ingress_log.log("Skipped (duplicate)", source, current_dest_path, summary)
                return True
            
            # Verify file exists
            if file_exists_in_docstore(current_dest_path):
                PaperSort.print_right(f"✓ Verified: {current_dest_path}")
                ingress_log.log("Skipped (duplicate)", source, current_dest_path, summary)
                return True
            
            # File missing, re-copy
            PaperSort.print_right(f"! File missing at {current_dest_path}, re-copying...")
            if copy_to_docstore(pdf_path, current_dest_path):
                PaperSort.print_right(f"✓ Re-copied to: {current_dest_path}")
                ingress_log.log("Filed (re-copied)", source, current_dest_path, summary)
                return True
            ingress_log.log("ERROR", source, current_dest_path, summary, "Re-copy failed")
            return False
        
        # File in wrong folder - needs move
        current_filename = os.path.basename(current_dest_path)
        new_dest_path = f"{resolved_path}/{current_filename}"
        
        PaperSort.print_right(f"Path changed: {current_folder} -> {resolved_path}")
        
        if file_exists_in_docstore(current_dest_path):
            if _move_in_docstore(current_dest_path, new_dest_path):
                dst_uri = _get_docstore_uri(new_dest_path)
                dst_display = f"{docstore_display}/{new_dest_path}"
                PaperSort.db.update_copied(meta.sha256, dst_uri, dst_display)
                PaperSort.print_right(f"✓ Moved to: {new_dest_path}")
                ingress_log.log("Filed (moved)", source, new_dest_path, summary)
                return True
            else:
                PaperSort.print_right("✗ Failed to move file")
                ingress_log.log("ERROR", source, new_dest_path, summary, "Move failed")
                return False
        else:
            # File missing, copy to new location
            PaperSort.print_right("! File missing at old location, copying to new...")
            if copy_to_docstore(pdf_path, new_dest_path):
                dst_uri = _get_docstore_uri(new_dest_path)
                dst_display = f"{docstore_display}/{new_dest_path}"
                PaperSort.db.update_copied(meta.sha256, dst_uri, dst_display)
                PaperSort.print_right(f"✓ Copied to: {new_dest_path}")
                ingress_log.log("Filed (re-copied)", source, new_dest_path, summary)
                return True
            ingress_log.log("ERROR", source, new_dest_path, summary, "Copy failed")
            return False
    
    # File not yet copied - copy to resolved path
    base_dest = f"{resolved_path}/{base_name}"
    hash_dest = f"{resolved_path}/{hash_name}"
    
    # Try base name first
    if not file_exists_in_docstore(base_dest):
        if copy_to_docstore(pdf_path, base_dest):
            dst_uri = _get_docstore_uri(base_dest)
            dst_display = f"{docstore_display}/{base_dest}"
            PaperSort.db.update_copied(meta.sha256, dst_uri, dst_display)
            PaperSort.print_right(f"✓ Copied to: {base_dest}")
            if PaperSort.log:
                _copy_to_incoming_log(pdf_path, meta.title, meta.reporting_year, meta.sha256)
            ingress_log.log("Filed successfully", source, base_dest, summary)
            return True
        ingress_log.log("ERROR", source, base_dest, summary, "Copy failed")
        return False
    
    # Check if hash name already exists
    if file_exists_in_docstore(hash_dest):
        dst_uri = _get_docstore_uri(hash_dest)
        dst_display = f"{docstore_display}/{hash_dest}"
        PaperSort.db.update_copied(meta.sha256, dst_uri, dst_display)
        PaperSort.print_right(f"✓ Already exists: {hash_dest}")
        ingress_log.log("Skipped (duplicate)", source, hash_dest, summary)
        return True
    
    # Name collision - use hash suffix
    if copy_to_docstore(pdf_path, hash_dest):
        dst_uri = _get_docstore_uri(hash_dest)
        dst_display = f"{docstore_display}/{hash_dest}"
        PaperSort.db.update_copied(meta.sha256, dst_uri, dst_display)
        PaperSort.print_right(f"✓ Copied to: {hash_dest}")
        if PaperSort.log:
            _copy_to_incoming_log(pdf_path, meta.title, meta.reporting_year, meta.sha256)
        ingress_log.log("Filed (renamed)", source, hash_dest, summary)
        return True
    ingress_log.log("ERROR", source, hash_dest, summary, "Copy failed")
    return False


def _log_filing(title: str, year: Optional[int], old_path: str, new_path: str) -> None:
    """Log a filing to the left panel."""
    timestamp = datetime.now().strftime("%H:%M")
    title_with_year = f"{title} {year}" if year else title
    old_dir = os.path.dirname(old_path) if '/' in old_path else old_path
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
    """Process all PDFs in a local inbox directory recursively."""
    if not os.path.exists(inbox_path):
        PaperSort.print_right(f"Inbox directory '{inbox_path}' does not exist")
        return
    
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
    
    inbox_name = os.path.basename(inbox_path)
    
    for i, filepath in enumerate(pdf_files, 1):
        PaperSort.set_progress(i, len(pdf_files))
        rel_path = os.path.relpath(filepath, inbox_path)
        PaperSort.print_right(f"\n--- {rel_path} ---")
        
        source = f"local:{inbox_path}:{rel_path}"
        readable_path = f"{inbox_name}/{rel_path}" if rel_path != os.path.basename(filepath) else inbox_name
        
        success = process_file(filepath, source=source, inbox_path=readable_path)
        
        if delete_on_success and success:
            try:
                os.unlink(filepath)
                PaperSort.print_right(f"✓ Deleted from inbox: {rel_path}")
            except Exception as e:
                PaperSort.print_right(f"✗ Failed to delete from inbox: {e}")


def process_gdrive_inbox(inbox_folder_id: str, delete_on_success: bool = False) -> None:
    """Process all PDFs in a Google Drive inbox folder recursively."""
    from storage import GDriveDriver, StorageError
    
    inbox_driver = GDriveDriver(inbox_folder_id)
    pdf_files = inbox_driver.list_files(recursive=True, extension=".pdf")
    
    if not pdf_files:
        PaperSort.print_right("No PDF files found in inbox")
        return
    
    PaperSort.print_right(f"Found {len(pdf_files)} PDF files in inbox")
    PaperSort.set_total_files(len(pdf_files))
    
    inbox_name = inbox_driver._root_folder_name or "Inbox"
    
    for i, file_info in enumerate(pdf_files, 1):
        PaperSort.set_progress(i, len(pdf_files))
        PaperSort.print_right(f"\n--- {file_info.path} ---")
        
        source = f"gdrive:{inbox_folder_id}:{file_info.path}"
        readable_path = f"{inbox_name}/{file_info.path}"
        
        temp_path = inbox_driver.download_to_temp(file_info.path)
        
        try:
            success = process_file(temp_path, cleanup_temp=True, source=source, inbox_path=readable_path)
            
            if delete_on_success and success:
                try:
                    inbox_driver.delete(file_info.path)
                    PaperSort.print_right(f"✓ Deleted from inbox: {file_info.path}")
                except StorageError as e:
                    PaperSort.print_right(f"✗ Failed to delete from inbox: {e}")
        except Exception as e:
            PaperSort.print_right(f"Error processing {file_info.name}: {str(e)}")
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def process_dropbox_inbox(inbox_path: str, delete_on_success: bool = False) -> None:
    """Process all PDFs in a Dropbox inbox folder recursively."""
    from storage import DropboxDriver, StorageError
    
    try:
        dbx = DropboxDriver(inbox_path)
    except StorageError as e:
        PaperSort.print_right(f"Error connecting to Dropbox: {str(e)}")
        return
    
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
    
    inbox_name = os.path.basename(inbox_path.rstrip('/')) or "Inbox"
    
    for i, file_info in enumerate(pdf_files, 1):
        PaperSort.set_progress(i, len(pdf_files))
        PaperSort.print_right(f"\n--- {file_info.path} ---")
        
        source = f"dropbox:{inbox_path}:{file_info.path}"
        readable_path = f"{inbox_name}/{file_info.path}"
        
        try:
            temp_path = dbx.download_to_temp(file_info.path)
        except StorageError as e:
            PaperSort.print_right(f"Error downloading {file_info.name}: {str(e)}")
            continue
        
        try:
            success = process_file(temp_path, cleanup_temp=True, source=source, inbox_path=readable_path)
            
            if delete_on_success and success:
                try:
                    dbx.delete(file_info.path)
                    PaperSort.print_right(f"✓ Deleted from inbox: {file_info.path}")
                except StorageError as e:
                    PaperSort.print_right(f"✗ Failed to delete from inbox: {e}")
        except Exception as e:
            PaperSort.print_right(f"Error processing {file_info.name}: {str(e)}")
            if os.path.exists(temp_path):
                os.unlink(temp_path)
