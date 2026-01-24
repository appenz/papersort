#!/usr/bin/env python3
"""PaperSort - Document filing assistant."""

import argparse
import os

from papersort import PaperSort, __version__
from workflows import (
    DocSorter,
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


def run_processing(inbox_uri: str, docstore_uri: str) -> None:
    """Run the document processing workflow.
    
    Args:
        inbox_uri: Inbox URI (e.g., 'gdrive:folder_id', 'local:path')
        docstore_uri: Docstore URI
    """
    # Load layout from docstore and get driver instance
    docstore_driver, docstore_name = load_layout(docstore_uri)
    PaperSort.docstore_driver = docstore_driver
    
    # Get inbox display name and type
    inbox_name, inbox_type, inbox_value = get_storage_display_name(inbox_uri)
    
    PaperSort.print_right(f"Using LLM provider: {PaperSort.llm_provider_name}")
    PaperSort.print_right(f"Docstore: {docstore_name}")
    PaperSort.print_right(f"Inbox: {inbox_name}")
    if PaperSort.update:
        PaperSort.print_right("Update mode: enabled (ignoring cache)")
    if PaperSort.copy:
        PaperSort.print_right("Copy mode: enabled" + (" (with verify)" if PaperSort.verify else ""))
    if PaperSort.log:
        PaperSort.print_right("Log mode: enabled (logging to --IncomingLog)")
    
    # Initialize database
    PaperSort.init_db()
    
    # Process inbox based on type
    if inbox_type == "gdrive":
        process_gdrive_inbox(inbox_value)
    elif inbox_type == "local":
        process_local_inbox(inbox_value)
    elif inbox_type == "dropbox":
        process_dropbox_inbox(inbox_value)
    else:
        PaperSort.print_right(f"Unknown inbox storage type: {inbox_type}")
    
    PaperSort.close()
    PaperSort.print_right("\n[green]Processing complete![/green]")


def main(inbox: str = None) -> None:
    """Main entry point for batch processing inbox (CLI mode).
    
    Uses PaperSort class variables for configuration.
    
    Args:
        inbox: Inbox URI (overrides INBOX env var if provided)
    """
    # Get configuration from environment
    docstore_uri = os.environ.get('DOCSTORE')
    inbox_uri = inbox or os.environ.get('INBOX')
    
    if not docstore_uri:
        print("Error: DOCSTORE environment variable not set")
        print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        return
    
    if not inbox_uri:
        print("Error: INBOX not specified")
        print("Use --inbox or set INBOX environment variable")
        print("Example: --inbox=gdrive:xyz789 or --inbox=local:inbox")
        return
    
    run_processing(inbox_uri, docstore_uri)


def main_tui(inbox: str = None) -> None:
    """Main entry point for batch processing inbox (TUI mode).
    
    Args:
        inbox: Inbox URI (overrides INBOX env var if provided)
    """
    from textui import PaperSortApp
    
    # Get configuration from environment
    docstore_uri = os.environ.get('DOCSTORE')
    inbox_uri = inbox or os.environ.get('INBOX')
    
    if not docstore_uri:
        print("Error: DOCSTORE environment variable not set")
        print("Example: DOCSTORE=gdrive:abc123 or DOCSTORE=local:docstore")
        return
    
    if not inbox_uri:
        print("Error: INBOX not specified")
        print("Use --inbox or set INBOX environment variable")
        print("Example: --inbox=gdrive:xyz789 or --inbox=local:inbox")
        return
    
    # Get display names for header (before starting TUI)
    inbox_name, _, _ = get_storage_display_name(inbox_uri)
    _, docstore_name = load_layout(docstore_uri)
    
    # Create processing function to pass to app
    def process_func():
        run_processing(inbox_uri, docstore_uri)
    
    # Create and run the TUI app
    app = PaperSortApp(
        source=inbox_name, 
        destination=docstore_name,
        process_func=process_func
    )
    app.run()


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
    parser.add_argument("--log", action="store_true",
                       help="Log incoming files to --IncomingLog folder (use with --copy)")
    parser.add_argument("--deduplicate", action="store_true", 
                       help="Find and merge duplicate company folders in the docstore")
    parser.add_argument("--inbox", type=str, 
                       help="Inbox URI (e.g., gdrive:folder_id, local:path, or dropbox:/path)")
    parser.add_argument("--auth-dropbox", action="store_true",
                       help="Authenticate with Dropbox (one-time setup)")
    parser.add_argument("--cli", action="store_true",
                       help="Use CLI output instead of TextUI (default is TextUI)")
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
            PaperSort.docstore_driver = docstore_driver
            PaperSort.llm_provider_name = os.environ.get('LLM_PROVIDER', 'mistral')
            
            print(f"Docstore: {docstore_name}")
            print(f"Using LLM provider: {PaperSort.llm_provider_name}")
            print("Starting deduplication...")
            
            deduplicate_company_folders()
    
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
            
            # Configure PaperSort from args
            PaperSort.configure(args, docstore_driver)
            
            print(f"Docstore: {docstore_name}")
            if PaperSort.copy:
                print("Copy mode: enabled" + (" (with verify)" if PaperSort.verify else ""))
            if PaperSort.log:
                print("Log mode: enabled (logging to --IncomingLog)")
            
            PaperSort.init_db()
            
            # Build source URI for single file (local file)
            source = f"local::{os.path.abspath(args.file)}"
            
            process_file(args.file, source=source)
            PaperSort.close()
    
    else:
        # Configure PaperSort from args (docstore_driver set later in main())
        PaperSort.configure(args)
        
        if args.cli:
            # CLI mode - plain text output
            main(inbox=args.inbox)
        else:
            # TUI mode (default) - Textual interface
            main_tui(inbox=args.inbox)
