from docsorter.docsorter import DocSorter
import os

def main():
    # Set the layout path explicitly
    layout_path = os.path.join('docstore', 'layout.txt')
    DocSorter.set_layout_path(layout_path)    

    # Get inbox directory from environment variable, default to "inbox"
    inbox_dir = os.environ.get('INBOX', 'inbox')
    
    # Ensure inbox directory exists
    if not os.path.exists(inbox_dir):
        print(f"Inbox directory '{inbox_dir}' does not exist")
        return

    # Process all PDF files in the inbox
    for filename in os.listdir(inbox_dir):
        if filename.lower().endswith('.pdf'):
            pdf_path = os.path.join(inbox_dir, filename)
            try:
                doc = DocSorter(pdf_path)
                doc.sort()
            except Exception as e:
                raise e
                print(f"Error processing {filename}: {str(e)}")
                continue

        # Print the filename in red
        print(f"\033[91mProcessed: {filename}\033[0m")
        print(doc)

        # Now check if the proposed path actually exists in the layout file
        if DocSorter.path_exists(doc.suggested_path):
            print(f"✓ Path '{doc.suggested_path}' exists in layout")
        else:
            print(f"✗ Path '{doc.suggested_path}' does not exist in layout")

if __name__ == "__main__":
    main()
