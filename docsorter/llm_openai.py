import base64
import os
from openai import OpenAI
from typing import Dict, List, Tuple, TYPE_CHECKING

from .docllm import LLMBase

if TYPE_CHECKING:
    from .docsorter import DocSorter


class OpenAILLM(LLMBase):
    """OpenAI implementation for document sorting."""
    
    def __init__(self):
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
    
    def build_messages(self, doc: "DocSorter") -> List[Dict]:
        """Build initial messages with base64-encoded PDF.
        
        Args:
            doc: The DocSorter instance containing the document to analyze.
            
        Returns:
            List of message dictionaries for the OpenAI API.
        """
        # Read and base64-encode the PDF
        with open(doc.previous_path, "rb") as f:
            pdf_bytes = f.read()
        base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
        
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
                        "type": "file",
                        "file": {
                            "filename": os.path.basename(doc.previous_path),
                            "file_data": f"data:application/pdf;base64,{base64_pdf}"
                        }
                    }
                ]
            }
        ]
    
    def complete(self, messages: List[Dict]) -> Tuple[str, List[Dict]]:
        """Send messages to OpenAI and return response with updated messages.
        
        Args:
            messages: The conversation messages to send.
            
        Returns:
            Tuple of (response_text, updated_messages).
        """
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        
        response_text = response.choices[0].message.content
        
        # Append assistant response to messages for potential follow-up
        updated_messages = messages + [
            {"role": "assistant", "content": response_text}
        ]
        
        return response_text, updated_messages
