from docsorter.docsorter import DocSorter
from docsorter.docindex import DocIndex, compute_sha256
import argparse
import os

def process_file(pdf_path, db, llm_provider, update=False):
    """Process a single PDF file, using cache if available."""
    filename = os.path.basename(pdf_path)
    
    if os.path.getsize(pdf_path) == 0:
        print(f"Skipping empty file: {filename}")
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
            doc.sort(llm_provider=llm_provider)
            doc.save_to_db(db)
            print(doc)
            path = doc.suggested_path
            if update and existing and existing.get('suggested_path') != path:
                print(f"\033[91mPath changed: {existing['suggested_path']} -> {path}\033[0m")
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            return
    
    if DocSorter.path_exists(path):
        print(f"✓ Path '{path}' exists in layout")
    else:
        print(f"✗ Path '{path}' does not exist in layout")

def main():
    layout_path = os.path.join('docstore', 'layout.txt')
    DocSorter.set_layout_path(layout_path)    
    db = DocIndex()
    inbox_dir = os.environ.get('INBOX', 'inbox')
    llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
    print(f"Using LLM provider: {llm_provider}")
    
    if not os.path.exists(inbox_dir):
        print(f"Inbox directory '{inbox_dir}' does not exist")
        return

    for filename in os.listdir(inbox_dir):
        if filename.lower().endswith('.pdf'):
            process_file(os.path.join(inbox_dir, filename), db, llm_provider)
    
    db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Document sorting utility")
    parser.add_argument("--showlayout", action="store_true", help="Print the document store layout")
    parser.add_argument("--file", type=str, help="Process a single file and exit")
    parser.add_argument("--update", action="store_true", help="Skip cache, reprocess and compare paths")
    args = parser.parse_args()

    if args.showlayout:
        layout_path = os.path.join('docstore', 'layout.txt')
        DocSorter.set_layout_path(layout_path)
        DocSorter.print_layout()
    elif args.file:
        layout_path = os.path.join('docstore', 'layout.txt')
        DocSorter.set_layout_path(layout_path)
        db = DocIndex()
        llm_provider = os.environ.get('LLM_PROVIDER', 'mistral')
        process_file(args.file, db, llm_provider, update=args.update)
        db.close()
    else:
        main()
