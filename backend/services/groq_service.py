import os
from groq import Groq
from typing import List, Dict, Any

class GroqService:
    """Handles interactions with Groq API"""
    
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.1-8b-instant"  # Fast model for chat
    
    def generate_answer(self, question: str, context_chunks: List[Dict[str, Any]], chat_history: List[Dict] = None) -> Dict[str, Any]:
        """Generate answer based on context chunks"""
        
        # Prepare context from chunks
        context = "\n\n".join([f"[Document {i+1}]: {chunk['text']}" for i, chunk in enumerate(context_chunks)])
        
        # Prepare system prompt
        system_prompt = """You are a helpful assistant that answers questions based on the provided documents. 
        Use only the information from the documents to answer questions. 
        If the answer cannot be found in the documents, say "I cannot find this information in the provided documents."
        Be concise and accurate."""
        
        # Prepare messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context documents:\n{context}\n\nQuestion: {question}"}
        ]
        
        # Add chat history if provided
        if chat_history:
            # Insert history after system message
            messages[1:1] = chat_history[-4:]  # Last 4 messages for context
        
        try:
            # Call Groq API
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=500,
                top_p=0.9
            )
            
            answer = completion.choices[0].message.content
            
            # Extract sources used
            sources = [
                {
                    "text": chunk['text'][:200] + "...",
                    "score": chunk.get('similarity_score', 0)
                }
                for chunk in context_chunks[:2]  # Top 2 sources
            ]
            
            return {
                "answer": answer,
                "sources": sources,
                "model": self.model
            }
            
        except Exception as e:
            raise Exception(f"Groq API error: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test if Groq API is working"""
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Say 'Connected to Groq API successfully!'"}],
                max_tokens=50
            )
            return True
        except Exception as e:
            print(f"Groq connection test failed: {e}")
            return False