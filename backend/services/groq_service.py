import os
from groq import Groq
from typing import List, Dict, Any

class GroqService:
    """Handles interactions with Groq API for real answers"""
    
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.1-8b-instant"
        print("🤖 Groq service initialized")
    
    def generate_answer(self, question: str, context_chunks: List[Dict[str, Any]], chat_history: List[Dict] = None) -> Dict[str, Any]:
        """Generate answer based on actual document context"""
        
        # Prepare context from chunks
        context = "\n\n".join([f"[Excerpt {i+1}]: {chunk['text']}" for i, chunk in enumerate(context_chunks)])
        
        # Prepare system prompt
        system_prompt = """You are a helpful assistant that answers questions based strictly on the provided document excerpts. 
        Follow these rules:
        1. Only use information from the provided excerpts to answer
        2. If the answer cannot be found in the excerpts, say "I cannot find this information in the document."
        3. Be concise and accurate
        4. Quote relevant parts when appropriate
        5. Do not make up information"""
        
        # Prepare user prompt
        user_prompt = f"""Document excerpts:
{context}

Question: {question}

Answer based only on the excerpts above:"""
        
        # Prepare messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Add chat history if provided
        if chat_history:
            # Insert history after system message
            messages[1:1] = chat_history[-4:]
        
        try:
            print(f"🤔 Asking Groq: {question}")
            
            # Call Groq API
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=500,
                top_p=0.9
            )
            
            answer = completion.choices[0].message.content
            print(f"✅ Got answer: {answer[:100]}...")
            
            # Extract sources used
            sources = [
                {
                    "text": chunk['text'][:200] + "...",
                    "score": chunk.get('similarity_score', 0)
                }
                for chunk in context_chunks[:3]
            ]
            
            return {
                "answer": answer,
                "sources": sources,
                "model": self.model
            }
            
        except Exception as e:
            print(f"❌ Groq API error: {str(e)}")
            raise Exception(f"Groq API error: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test if Groq API is working"""
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Say 'OK' if you can hear me"}],
                max_tokens=10
            )
            return True
        except Exception as e:
            print(f"❌ Groq connection test failed: {e}")
            return False