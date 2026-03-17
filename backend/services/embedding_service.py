from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List, Dict, Any

class EmbeddingService:
    """Handles text embedding generation using sentence transformers"""
    
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """Initialize the embedding model"""
        print(f"🔄 Loading embedding model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        print(f"✅ Model loaded! Embedding dimension: {self.embedding_dim}")
    
    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        embedding = self.model.encode(text)
        return embedding.tolist()
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        embeddings = self.model.encode(texts, show_progress_bar=True)
        return embeddings.tolist()
    
    def generate_chunk_embeddings(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate embeddings for document chunks"""
        texts = [chunk['text'] for chunk in chunks]
        print(f"🔢 Generating embeddings for {len(texts)} chunks...")
        
        embeddings = self.generate_embeddings(texts)
        
        # Add embeddings to chunks
        for i, chunk in enumerate(chunks):
            chunk['embedding'] = embeddings[i]
        
        print("✅ Embeddings generated successfully")
        return chunks