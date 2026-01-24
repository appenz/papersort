"""Repair workflow for fixing metadata cache and handling duplicates."""

import os
from datetime import datetime
from typing import Optional

from papersort import PaperSort
from .metadata_cache import compute_sha256


def _log_repair(title: Optional[str], year: Optional[int], 
                old_path: str, action: str) -> None:
    """Log a repair action to the left panel."""
    timestamp = datetime.now().strftime("%H:%M")
    if title:
        title_with_year = f"{title} {year}" if year else title
    else:
        title_with_year = os.path.basename(old_path)
    line1 = f"{timestamp} {title_with_year}"
    line2 = f"  {action}"
    PaperSort.print_left(line1, line2)


def repair_cache() -> None:
    """Scan docstore and repair metadata cache.
    
    - Updates copied/dest_path for files found in docstore
    - Detects and handles duplicates
    - Skips folders starting with '--'
    """
    driver = PaperSort.docstore_driver
    if not driver:
        PaperSort.print_right("Error: No docstore driver configured")
        return
    
    PaperSort.print_right("Scanning docstore for PDF files...")
    all_files = driver.list_files(recursive=True, extension=".pdf")
    
    # Filter out files in folders starting with "--"
    files = [f for f in all_files if not _in_system_folder(f.path)]
    
    PaperSort.print_right(f"Found {len(files)} PDF files (excluding system folders)")
    PaperSort.set_total_files(len(files))
    
    repaired = 0
    duplicates_moved = 0
    duplicates_skipped = 0
    
    for i, file_info in enumerate(files, 1):
        scan_path = file_info.path
        PaperSort.set_progress(i, len(files))
        PaperSort.print_right(f"\n[{i}/{len(files)}] {scan_path}")
        
        # Download to compute hash
        try:
            temp_path = driver.download_to_temp(scan_path)
        except Exception as e:
            PaperSort.print_right(f"  Error downloading: {e}")
            continue
        
        try:
            file_hash = compute_sha256(temp_path)
        finally:
            os.unlink(temp_path)
        
        # Look up in database
        existing = PaperSort.db.get_by_hash(file_hash)
        
        if not existing:
            PaperSort.print_right(f"  Not in cache (needs processing)")
            continue
        
        db_dest_path = existing.get('dest_path')
        db_copied = existing.get('copied')
        suggested_path = existing.get('suggested_path')
        
        # Case 1: No dest_path recorded - just update
        if not db_dest_path:
            _update_dest_path(file_hash, scan_path)
            PaperSort.print_right(f"  [green]Updated: dest_path was empty[/green]")
            _log_repair(existing.get('title'), existing.get('year'), 
                       scan_path, f"→ {scan_path}")
            repaired += 1
            continue
        
        # Case 2: dest_path matches scan_path - ensure copied=1
        scan_folder = os.path.dirname(scan_path)
        db_folder = os.path.dirname(db_dest_path)
        
        if db_dest_path == scan_path:
            if not db_copied:
                PaperSort.db.update_copied(file_hash, scan_path)
                PaperSort.print_right(f"  [green]Fixed: copied flag was 0[/green]")
                _log_repair(existing.get('title'), existing.get('year'),
                           scan_path, "Fixed: copied flag")
                repaired += 1
            else:
                PaperSort.print_right(f"  OK")
            continue
        
        # Case 3: dest_path differs - check for duplicate
        if driver.file_exists(db_dest_path):
            # Duplicate detected!
            PaperSort.print_right(f"  [yellow]Duplicate! Also exists at: {db_dest_path}[/yellow]")
            
            # Check which one matches suggested_path
            if suggested_path:
                suggested_folder = suggested_path
                
                if scan_folder == suggested_folder:
                    # Keep scan_path, move db_dest_path to --Duplicate
                    if _move_to_duplicate(db_dest_path):
                        _update_dest_path(file_hash, scan_path)
                        PaperSort.print_right(f"  [green]Moved to --Duplicate[/green]")
                        _log_repair(existing.get('title'), existing.get('year'),
                                   db_dest_path, f"{db_dest_path} → --Duplicate")
                        duplicates_moved += 1
                    continue
                    
                elif db_folder == suggested_folder:
                    # Keep db_dest_path, move scan_path to --Duplicate
                    if _move_to_duplicate(scan_path):
                        PaperSort.print_right(f"  [green]Moved to --Duplicate[/green]")
                        _log_repair(existing.get('title'), existing.get('year'),
                                   scan_path, f"{scan_path} → --Duplicate")
                        duplicates_moved += 1
                    continue
            
            # Neither matches suggested_path (or no suggested_path)
            PaperSort.print_right(f"  [red]Skipping - manual review needed[/red]")
            duplicates_skipped += 1
        else:
            # File doesn't exist at db_dest_path, update to scan_path
            _update_dest_path(file_hash, scan_path)
            PaperSort.print_right(f"  [green]Updated: file was not at recorded location[/green]")
            _log_repair(existing.get('title'), existing.get('year'),
                       scan_path, f"{db_dest_path} → {scan_path}")
            repaired += 1
    
    PaperSort.print_right(f"\n=== Repair Summary ===")
    PaperSort.print_right(f"Records repaired: {repaired}")
    PaperSort.print_right(f"Duplicates moved to --Duplicate: {duplicates_moved}")
    PaperSort.print_right(f"Duplicates skipped (manual review needed): {duplicates_skipped}")


def _in_system_folder(path: str) -> bool:
    """Check if path is inside a folder starting with '--'."""
    parts = path.split('/')
    return any(part.startswith('--') for part in parts)


def _update_dest_path(file_hash: str, dest_path: str) -> None:
    """Update the dest_path and set copied=1."""
    PaperSort.db.update_copied(file_hash, dest_path)


def _move_to_duplicate(file_path: str) -> bool:
    """Move a file to the --Duplicate folder."""
    try:
        PaperSort.docstore_driver.move(file_path, "--Duplicate")
        return True
    except Exception as e:
        PaperSort.print_right(f"  [red]Error moving to --Duplicate: {e}[/red]")
        return False
