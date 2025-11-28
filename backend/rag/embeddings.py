"""
Embeddings utilities for the RAG system.
Uses sentence-transformers for local embeddings or OpenAI for API-based embeddings.
"""

from typing import List, Optional
import os


class EmbeddingProvider:
    """
    Embedding provider that supports multiple backends.
    Default: Uses ChromaDB's built-in embeddings (all-MiniLM-L6-v2)
    Optional: OpenAI embeddings for higher quality
    """
    
    def __init__(self, provider: str = "default"):
        """
        Initialize the embedding provider.
        
        Args:
            provider: "default" (ChromaDB built-in), "openai", or "sentence-transformers"
        """
        self.provider = provider
        self.model = None
        
        if provider == "openai":
            self._init_openai()
        elif provider == "sentence-transformers":
            self._init_sentence_transformers()
    
    def _init_openai(self):
        """Initialize OpenAI embeddings."""
        try:
            from openai import OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            self.client = OpenAI(api_key=api_key)
            self.model_name = "text-embedding-3-small"
        except ImportError:
            raise ImportError("OpenAI package not installed. Run: pip install openai")
    
    def _init_sentence_transformers(self):
        """Initialize sentence-transformers embeddings."""
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
        except ImportError:
            raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")
    
    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: The text to embed
            
        Returns:
            List of floats representing the embedding
        """
        if self.provider == "openai":
            response = self.client.embeddings.create(
                input=text,
                model=self.model_name
            )
            return response.data[0].embedding
        elif self.provider == "sentence-transformers":
            return self.model.encode(text).tolist()
        else:
            # For default, we don't generate embeddings directly
            # ChromaDB handles this internally
            raise NotImplementedError("Use ChromaDB's built-in embedding function")
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embeddings
        """
        if self.provider == "openai":
            response = self.client.embeddings.create(
                input=texts,
                model=self.model_name
            )
            return [item.embedding for item in response.data]
        elif self.provider == "sentence-transformers":
            return self.model.encode(texts).tolist()
        else:
            raise NotImplementedError("Use ChromaDB's built-in embedding function")


def get_embedding_function(provider: str = "default"):
    """
    Get an embedding function compatible with ChromaDB.
    
    Args:
        provider: The embedding provider to use
        
    Returns:
        An embedding function or None (for ChromaDB default)
    """
    if provider == "default":
        # Use ChromaDB's default embedding function
        return None
    
    embedding_provider = EmbeddingProvider(provider)
    
    class CustomEmbeddingFunction:
        def __call__(self, input: List[str]) -> List[List[float]]:
            return embedding_provider.embed_texts(input)
    
    return CustomEmbeddingFunction()
