"""
FAQ RAG (Retrieval-Augmented Generation) system for answering clinic-related questions.
"""

from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json

from .vector_store import VectorStore, initialize_vector_store


class FAQRAG:
    """
    RAG system for retrieving and answering clinic FAQs.
    """
    
    def __init__(self, persist_directory: str = "./data/vectordb"):
        """
        Initialize the FAQ RAG system.
        
        Args:
            persist_directory: Directory for vector store persistence
        """
        self.vector_store = initialize_vector_store(persist_directory)
        self.confidence_threshold = 0.5  # Minimum similarity for a valid answer
        
        # Load clinic data for additional context
        data_dir = Path(__file__).parent.parent.parent / "data"
        clinic_info_path = data_dir / "clinic_info.json"
        
        with open(clinic_info_path, "r") as f:
            self.clinic_data = json.load(f)
    
    def is_faq_question(self, query: str) -> bool:
        """
        Determine if a query is likely an FAQ question vs. a scheduling request.
        
        Args:
            query: The user's query
            
        Returns:
            True if likely an FAQ question, False otherwise
        """
        # Keywords that suggest FAQ intent
        faq_keywords = [
            "where", "location", "address", "parking", "directions",
            "hours", "open", "close", "when",
            "insurance", "accept", "payment", "pay", "cost", "price", "billing",
            "bring", "documents", "prepare", "first visit",
            "cancel", "cancellation", "policy", "policies",
            "covid", "mask", "protocol",
            "late", "arrive", "early",
            "telehealth", "virtual", "video",
            "contact", "phone", "email", "call"
        ]
        
        # Keywords that suggest scheduling intent
        scheduling_keywords = [
            "book", "schedule", "appointment", "see the doctor",
            "available", "slot", "time", "tomorrow", "today",
            "reschedule", "change my appointment"
        ]
        
        query_lower = query.lower()
        
        faq_score = sum(1 for kw in faq_keywords if kw in query_lower)
        scheduling_score = sum(1 for kw in scheduling_keywords if kw in query_lower)
        
        # If the query contains "do you" or "what is" or "how", it's likely FAQ
        question_patterns = ["do you", "what is", "what are", "how do", "how can", "where is", "where are", "is there", "can i"]
        for pattern in question_patterns:
            if pattern in query_lower:
                faq_score += 2
        
        return faq_score > scheduling_score
    
    def retrieve(
        self,
        query: str,
        n_results: int = 3,
        category: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve relevant FAQ entries for a query.
        
        Args:
            query: The user's question
            n_results: Number of results to retrieve
            category: Optional category filter
            
        Returns:
            List of relevant FAQ entries with metadata
        """
        where_filter = {"category": category} if category else None
        
        results = self.vector_store.query(
            query_text=query,
            n_results=n_results,
            where=where_filter
        )
        
        retrieved = []
        for i, doc in enumerate(results["documents"]):
            metadata = results["metadatas"][i] if results["metadatas"] else {}
            distance = results["distances"][i] if results["distances"] else 1.0
            
            # Convert distance to similarity (ChromaDB uses cosine distance)
            similarity = 1 - distance
            
            retrieved.append({
                "content": doc,
                "question": metadata.get("question", ""),
                "answer": metadata.get("answer", doc),
                "category": metadata.get("category", "General"),
                "similarity": similarity,
                "id": results["ids"][i] if results["ids"] else f"doc-{i}"
            })
        
        return retrieved
    
    def get_answer(self, query: str) -> Tuple[str, float, List[Dict]]:
        """
        Get an answer for a FAQ query.
        
        Args:
            query: The user's question
            
        Returns:
            Tuple of (answer, confidence, sources)
        """
        # Retrieve relevant documents
        results = self.retrieve(query, n_results=3)
        
        if not results:
            return self._get_fallback_answer(), 0.0, []
        
        # Get the best match
        best_match = results[0]
        confidence = best_match["similarity"]
        
        if confidence < self.confidence_threshold:
            # Low confidence - provide general help
            answer = self._get_fallback_answer()
            return answer, confidence, results
        
        # Use the answer from the best match
        answer = best_match["answer"]
        
        # If there are highly relevant additional results, we could combine them
        # For now, just use the best match
        
        return answer, confidence, results
    
    def _get_fallback_answer(self) -> str:
        """Get a fallback answer when no good match is found."""
        clinic = self.clinic_data.get("clinic", {})
        return (
            f"I'm not sure about that specific question, but I'd be happy to help! "
            f"You can reach our clinic at {clinic.get('phone', 'our main number')} "
            f"or email us at {clinic.get('email', 'our office email')} for more information. "
            f"Is there anything else I can help you with, or would you like to schedule an appointment?"
        )
    
    def get_clinic_info(self, info_type: str) -> Optional[Dict]:
        """
        Get structured clinic information.
        
        Args:
            info_type: Type of info to retrieve (location, hours, insurance, policies)
            
        Returns:
            Dictionary with the requested information
        """
        return self.clinic_data.get(info_type)
    
    def format_answer_for_chat(self, query: str) -> str:
        """
        Format an FAQ answer for chat response.
        
        Args:
            query: The user's question
            
        Returns:
            Formatted answer string
        """
        answer, confidence, sources = self.get_answer(query)
        
        # If confidence is very high, just return the answer
        if confidence > 0.8:
            return answer
        
        # If moderate confidence, return with slight hedging
        if confidence > self.confidence_threshold:
            return answer
        
        # Low confidence - return fallback
        return answer


# Singleton instance
_faq_rag_instance: Optional[FAQRAG] = None


def get_faq_rag(persist_directory: str = "./data/vectordb") -> FAQRAG:
    """
    Get or create the FAQ RAG instance.
    
    Args:
        persist_directory: Directory for vector store persistence
        
    Returns:
        FAQRAG instance
    """
    global _faq_rag_instance
    if _faq_rag_instance is None:
        _faq_rag_instance = FAQRAG(persist_directory)
    return _faq_rag_instance
