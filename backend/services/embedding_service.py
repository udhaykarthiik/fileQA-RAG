from fastembed import TextEmbedding
import numpy as np
from typing import List, Dict, Any

class EmbeddingService:
    """Handles text embedding generation using fastembed (no torch dependency)"""

    def __init__(self, model_name='sentence-transformers/paraphrase-MiniLM-L3-v2'):
        """Initialize the embedding model"""
        print(f"🔄 Loading embedding model: {model_name}...")
        self.model = TextEmbedding(model_name=model_name)

        # fastembed doesn't expose dimension directly, so we get it from a test encode
        test = list(self.model.embed(["test"]))
        self.embedding_dim = len(test[0])
        print(f"✅ Model loaded! Embedding dimension: {self.embedding_dim}")

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        result = list(self.model.embed([text]))
        return result[0].tolist()

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        results = list(self.model.embed(texts))
        return [r.tolist() for r in results]

    def generate_chunk_embeddings(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate embeddings for document chunks"""
        texts = [chunk['text'] for chunk in chunks]
        print(f"🔢 Generating embeddings for {len(texts)} chunks...")

        embeddings = self.generate_embeddings(texts)

        for i, chunk in enumerate(chunks):
            chunk['embedding'] = embeddings[i]

        print("✅ Embeddings generated successfully")
        return chunks