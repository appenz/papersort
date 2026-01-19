import os
from mistralai import Mistral
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from .docsorter import DocSorter

def try_sort(doc: "DocSorter") -> None:
    api_key = os.environ["MISTRAL_API_KEY"]
    client = Mistral(api_key=api_key)
    
    # First upload the document to get a signed URL
    with open(doc.previous_path, 'rb') as file:
        upload_response = client.files.upload(
            file={
                    "file_name": "uploaded_file.pdf",
                    "content": file,
                },
            purpose="ocr"
        )
    
    #print(upload_response)
    client.files.retrieve(file_id=upload_response.id)
    
    # Get the signed URL for the uploaded document
    signed_url = client.files.get_signed_url(file_id=upload_response.id)
    #print(signed_url)
    
    prompt = doc.get_static_prompt() + doc.get_layout()
    prompt += "---\nOne last hint, in a different place this document was filed as: " + doc.previous_path

    # Create chat completion with document analysis prompt
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "document_url",
                    "document_url": signed_url.url
                }
            ]
        }
    ]
    
    chat_response = client.chat.complete(
        model="mistral-small-latest",
        messages=messages
    )
    
    return chat_response.choices[0].message.content

def result_to_dict(result: str) -> Dict[str, str]:
    """Converts the LLM response into a dictionary of metadata fields.
    
    Expected format:
    TITLE: <title>
    SUGGESTED_PATH: <path>
    CONFIDENCE: <confidence>
    YEAR: <year>
    DATE: <date>
    ENTITY: <entity>
    SUMMARY: <summary>
    """
    result_dict = {}
    
    # Split the text into lines and process each line
    for line in result.split('\n'):
        line = line.strip()
        
        # Skip empty lines and separator lines
        if not line or line.startswith('---'):
            continue
            
        # Split on first colon
        parts = line.split(':', 1)
        if len(parts) != 2:
            continue
            
        key = parts[0].strip()
        value = parts[1].strip()
        
        # Store in dictionary if it's one of our expected fields
        if key in ['TITLE', 'SUGGESTED_PATH', 'CONFIDENCE', 'YEAR', 'DATE', 'ENTITY', 'SUMMARY', ]:
            result_dict[key] = value
    
    if len(result_dict) != 7:
        # Print which fields are missing
        missing_fields = set(['TITLE', 'SUGGESTED_PATH', 'CONFIDENCE', 'YEAR', 'DATE', 'ENTITY', 'SUMMARY']) - set(result_dict.keys())
        print(f"Incorrect format. Missing fields: {missing_fields}")
        return None

    return result_dict

def sort(doc: "DocSorter") -> None:
    """Analyzes document and populates metadata fields"""
    
    result = try_sort(doc)
    result_dict = result_to_dict(result)
    if result_dict is None:
        print("Error: LLM did not return a valid result.")
        return

    doc.title = result_dict['TITLE']
    doc.suggested_path = result_dict['SUGGESTED_PATH']
    doc.confidence = result_dict['CONFIDENCE']
    doc.year = result_dict['YEAR']
    doc.date = result_dict['DATE']
    doc.entity = result_dict['ENTITY']
    doc.summary = result_dict['SUMMARY']
