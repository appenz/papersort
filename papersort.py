#!/usr/bin/env python3
"""PaperSort - Document filing assistant.

CLI entry point that dispatches to workflows for document processing.
"""

import argparse
import os

from workflows import (
    DocSorter,
    MetadataCache,
    process_file,
    process_local_inbox,
    process_gdrive_inbox,
    process_dropbox_inbox,
    deduplicate_company_folders,
)
from storage import (
    create_storage,
    parse_storage_uri,
    StorageError,
    GDriveDriver,
    DropboxDriver,
    authenticate_dropbox,
)


def get_storage_display_name(uri: str) -> tuple:
    """Get a human-readable display name for a storage URI.
    
    Args:
        uri: Storage URI (e.g., 'gdrive:folder_id', 'local:path', or 'dropbox:/path')
        
    Returns:
        Tuple of (display_name, storage_type, value)
    """
    storage_type, value = parse_storage_uri(uri)
    
    if storage_type == "gdrive":
        driver = GDriveDriver(value)
        return (driver.display_name, storage_type, value)
    elif storage_type == "local":
        return (f"{value} (local)", storage_type, value)
    elif storage_type == "dropbox":
        try:
            driver = DropboxDriver(value)
            return (driver.display_name, storage_type, value)
        except StorageError:
            return (f"{value} (Dropbox)", storage_type, value)
    else:
        return (uri, storage_type, value)


def load_layout(docstore_uri: str) -> tuple:
    """Load layout.txt from the docstore location.
    
    Args:
        docstore_uri: Storage URI (e.g., 'gdrive:folder_id' or 'local:path')
        
    Returns:
        Tuple of (StorageDriver instance, display_name)
    """
    driver = create_storage(docstore_uri)
    layout_content = driver.read_text("layout.txt")
    DocSorter.set_layout_content(layout_content)
    return (driver, driver.display_name)


def main(update: bool = False, copy: bool = False, verify: bool = False, 
         inbox: str = None) -> None:
    """Main entry point for batch processing inbox.
    
    Args:
        update: If True, reprocess even if cached
        copy: If True, copy files to docstore after processing
        verify: If True, verify files exist at destination
        inbox: Inbox URI (overrides INBOX env var if provided)
    """
    # Get configuration from environment
    docstore_uri = os.environ.get('DOCSTORE')
    inbox_uri = inbox or os.environ.get('INBOX')
    llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
    
    if not docstore_uri:
        print("Error: DOCSTORE environment variable not set")
        print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        return
    
    if not inbox_uri:
        print("Error: INBOX not specified")
        print("Use --inbox or set INBOX environment variable")
        print("Example: --inbox=gdrive:xyz789 or --inbox=local:inbox")
        return
    
    # Load layout from docstore and get driver instance
    docstore_driver, docstore_name = load_layout(docstore_uri)
    
    # Get inbox display name and type
    inbox_name, inbox_type, inbox_value = get_storage_display_name(inbox_uri)
    
    print(f"Using LLM provider: {llm_provider}")
    print(f"Docstore: {docstore_name}")
    print(f"Inbox: {inbox_name}")
    if update:
        print("Update mode: enabled (ignoring cache)")
    if copy:
        print("Copy mode: enabled" + (" (with verify)" if verify else ""))
    
    # Initialize database
    db = MetadataCache()
    
    # Process inbox based on type
    if inbox_type == "gdrive":
        process_gdrive_inbox(inbox_value, db, llm_provider, update=update,
                            copy=copy, verify=verify,
                            docstore_driver=docstore_driver)
    elif inbox_type == "local":
        process_local_inbox(inbox_value, db, llm_provider, update=update,
                           copy=copy, verify=verify,
                           docstore_driver=docstore_driver)
    elif inbox_type == "dropbox":
        process_dropbox_inbox(inbox_value, db, llm_provider, update=update,
                             copy=copy, verify=verify,
                             docstore_driver=docstore_driver)
    else:
        print(f"Unknown inbox storage type: {inbox_type}")
    
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Document sorting utility")
    parser.add_argument("--showlayout", action="store_true", 
                       help="Print the document store layout")
    parser.add_argument("--file", type=str, 
                       help="Process a single file and exit")
    parser.add_argument("--update", action="store_true", 
                       help="Skip cache, reprocess and compare paths")
    parser.add_argument("--copy", action="store_true", 
                       help="Copy files to docstore after processing")
    parser.add_argument("--verify", action="store_true", 
                       help="Verify files exist at destination (use with --copy)")
    parser.add_argument("--deduplicate", action="store_true", 
                       help="Find and merge duplicate company folders in the docstore")
    parser.add_argument("--inbox", type=str, 
                       help="Inbox URI (e.g., gdrive:folder_id, local:path, or dropbox:/path)")
    parser.add_argument("--auth-dropbox", action="store_true",
                       help="Authenticate with Dropbox (one-time setup)")
    args = parser.parse_args()

    # Handle --auth-dropbox first (doesn't need DOCSTORE)
    if args.auth_dropbox:
        print("=== Dropbox Authentication Setup ===")
        print()
        print("You need your Dropbox app credentials.")
        print("If you don't have an app yet, create one at: https://www.dropbox.com/developers/apps")
        print()
        print("App settings required:")
        print("  - Permission type: Scoped access")
        print("  - Access type: Full Dropbox")
        print("  - Permissions: files.metadata.read, files.content.read")
        print()
        
        app_key = input("Enter your App key: ").strip()
        app_secret = input("Enter your App secret: ").strip()
        
        if not app_key or not app_secret:
            print("Error: App key and secret are required")
        else:
            authenticate_dropbox(app_key, app_secret)
        
        exit(0)

    # Get docstore from environment
    docstore_uri = os.environ.get('DOCSTORE')
    
    if args.deduplicate:
        if not docstore_uri:
            print("Error: DOCSTORE environment variable not set")
            print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        else:
            docstore_driver, docstore_name = load_layout(docstore_uri)
            
            llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
            
            print(f"Docstore: {docstore_name}")
            print(f"Using LLM provider: {llm_provider}")
            print("Starting deduplication...")
            
            deduplicate_company_folders(docstore_driver, llm_provider)
    
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
            docstore_driver, docstore_name = load_layout(docstore_uri)
            
            print(f"Docstore: {docstore_name}")
            if args.copy:
                print("Copy mode: enabled" + (" (with verify)" if args.verify else ""))
            
            db = MetadataCache()
            llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
            
            # Build source URI for single file (local file)
            source = f"local::{os.path.abspath(args.file)}"
            
            process_file(args.file, db, llm_provider, update=args.update,
                        copy=args.copy, verify=args.verify, source=source,
                        docstore_driver=docstore_driver)
            db.close()
    
    else:
        main(update=args.update, copy=args.copy, verify=args.verify, inbox=args.inbox)
