import os
from mistralai import Mistral
from typing import Dict, List, Tuple, TYPE_CHECKING

from .docllm import LLMBase

if TYPE_CHECKING:
    from .docsorter import DocSorter


class MistralLLM(LLMBase):
    """Mistral AI implementation for document sorting."""
    
    def __init__(self):
        api_key = os.environ["MISTRAL_API_KEY"]
        self.client = Mistral(api_key=api_key)
    
    def build_messages(self, doc: "DocSorter") -> List[Dict]:
        """Build initial messages with uploaded document URL.
        
        Uses Mistral's file upload API to get a signed URL for the document.
        
        Args:
            doc: The DocSorter instance containing the document to analyze.
            
        Returns:
            List of message dictionaries for the Mistral API.
        """
        # Upload the document to get a signed URL
        with open(doc.previous_path, 'rb') as file:
            upload_response = self.client.files.upload(
                file={
                    "file_name": "uploaded_file.pdf",
                    "content": file,
                },
                purpose="ocr"
            )
        
        self.client.files.retrieve(file_id=upload_response.id)
        signed_url = self.client.files.get_signed_url(file_id=upload_response.id)
        
        prompt = doc.get_static_prompt() + doc.get_layout()
        prompt += "---\nOne last hint, in a different place this document was filed as: " + doc.previous_path

        return [
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
    
    def complete(self, messages: List[Dict]) -> Tuple[str, List[Dict]]:
        """Send messages to Mistral and return response with updated messages.
        
        Args:
            messages: The conversation messages to send.
            
        Returns:
            Tuple of (response_text, updated_messages).
        """
        chat_response = self.client.chat.complete(
            model="mistral-small-latest",
            messages=messages
        )
        
        response_text = chat_response.choices[0].message.content
        
        # Append assistant response to messages for potential follow-up
        updated_messages = messages + [
            {"role": "assistant", "content": response_text}
        ]
        
        return response_text, updated_messages
