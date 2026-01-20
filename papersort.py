from docsorter.docsorter import DocSorter
from docsorter.docindex import DocIndex, compute_sha256
from gdrive.gdrive import GDrive, parse_storage_uri
import argparse
import os

# Global GDrive instance for inbox operations (if using gdrive inbox)
_inbox_drive = None


def process_file(pdf_path, db, llm_provider, update=False, cleanup_temp=False):
    """Process a single PDF file, using cache if available.
    
    Args:
        pdf_path: Path to the PDF file (local path)
        db: DocIndex database instance
        llm_provider: LLM provider to use
        update: If True, reprocess even if cached
        cleanup_temp: If True, delete the file after processing (for temp files)
    """
    filename = os.path.basename(pdf_path)
    
    if os.path.getsize(pdf_path) == 0:
        print(f"Skipping empty file: {filename}")
        if cleanup_temp:
            os.unlink(pdf_path)
        return
    
    file_hash = compute_sha256(pdf_path)
    existing = db.get_by_hash(file_hash)
    
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
        path = existing['suggested_path']
    else:
        try:
            print(f"\033[91mProcessing: {filename}\033[0m")
            doc = DocSorter(pdf_path)
            if not doc.sort(llm_provider=llm_provider):
                if cleanup_temp:
                    os.unlink(pdf_path)
                return
            doc.save_to_db(db)
            print(doc)
            path = doc.suggested_path
            if update and existing and existing.get('suggested_path') != path:
                print(f"\033[91mPath changed: {existing['suggested_path']} -> {path}\033[0m")
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            if cleanup_temp:
                os.unlink(pdf_path)
            return
    
    if DocSorter.path_exists(path):
        print(f"✓ Path '{path}' exists in layout")
    else:
        print(f"✗ Path '{path}' does not exist in layout")
    
    if cleanup_temp:
        os.unlink(pdf_path)


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


def process_local_inbox(inbox_path, db, llm_provider):
    """Process all PDFs in a local inbox directory recursively.
    
    Args:
        inbox_path: Local path to inbox directory
        db: DocIndex database instance
        llm_provider: LLM provider to use
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
                process_file(filepath, db, llm_provider)


def process_gdrive_inbox(inbox_folder_id, db, llm_provider):
    """Process all PDFs in a Google Drive inbox folder recursively.
    
    Args:
        inbox_folder_id: Google Drive folder ID for inbox
        db: DocIndex database instance
        llm_provider: LLM provider to use
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
        
        # Download to temp file
        temp_path = _inbox_drive.download_to_temp(file_info['id'], file_info['name'])
        
        try:
            # Process the file (cleanup_temp=True to delete after)
            process_file(temp_path, db, llm_provider, cleanup_temp=True)
        except Exception as e:
            print(f"Error processing {file_info['name']}: {str(e)}")
            # Ensure temp file is cleaned up even on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def main():
    """Main entry point for batch processing inbox."""
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
    
    # Load layout from docstore and get display name
    _, docstore_name = load_layout(docstore_uri)
    
    # Get inbox display name
    inbox_name, inbox_type, inbox_value = get_storage_display_name(inbox_uri)
    
    print(f"Using LLM provider: {llm_provider}")
    print(f"Docstore: {docstore_name}")
    print(f"Inbox: {inbox_name}")
    
    # Initialize database
    db = DocIndex()
    
    # Process inbox based on type
    if inbox_type == "gdrive":
        process_gdrive_inbox(inbox_value, db, llm_provider)
    elif inbox_type == "local":
        process_local_inbox(inbox_value, db, llm_provider)
    else:
        print(f"Unknown inbox storage type: {inbox_type}")
    
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Document sorting utility")
    parser.add_argument("--showlayout", action="store_true", help="Print the document store layout")
    parser.add_argument("--file", type=str, help="Process a single file and exit")
    parser.add_argument("--update", action="store_true", help="Skip cache, reprocess and compare paths")
    args = parser.parse_args()

    # Get docstore from environment
    docstore_uri = os.environ.get('DOCSTORE')
    
    if args.showlayout:
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
            _, docstore_name = load_layout(docstore_uri)
            print(f"Docstore: {docstore_name}")
            db = DocIndex()
            llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
            process_file(args.file, db, llm_provider, update=args.update)
            db.close()
    else:
        main()
