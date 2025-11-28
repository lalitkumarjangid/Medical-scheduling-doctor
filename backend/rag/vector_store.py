"""
Vector store implementation using ChromaDB for FAQ retrieval.
"""

import chromadb
from chromadb.config import Settings
from pathlib import Path
from typing import List, Dict, Optional
import json


class VectorStore:
    """ChromaDB-based vector store for FAQ documents."""
    
    def __init__(self, persist_directory: Optional[str] = None):
        """
        Initialize the vector store.
        
        Args:
            persist_directory: Directory to persist the database. If None, uses in-memory storage.
        """
        if persist_directory:
            Path(persist_directory).mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=persist_directory)
        else:
            self.client = chromadb.Client()
        
        self.collection_name = "clinic_faqs"
        self.collection = None
    
    def get_or_create_collection(self):
        """Get existing collection or create a new one."""
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        return self.collection
    
    def add_documents(
        self,
        documents: List[str],
        metadatas: List[Dict],
        ids: List[str]
    ) -> None:
        """
        Add documents to the vector store.
        
        Args:
            documents: List of document texts
            metadatas: List of metadata dicts for each document
            ids: List of unique IDs for each document
        """
        if self.collection is None:
            self.get_or_create_collection()
        
        # ChromaDB will use its default embedding function (all-MiniLM-L6-v2)
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
    
    def query(
        self,
        query_text: str,
        n_results: int = 3,
        where: Optional[Dict] = None
    ) -> Dict:
        """
        Query the vector store for similar documents.
        
        Args:
            query_text: The query text
            n_results: Number of results to return
            where: Optional filter conditions
            
        Returns:
            Dictionary with documents, metadatas, distances, and ids
        """
        if self.collection is None:
            self.get_or_create_collection()
        
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where
        )
        
        return {
            "documents": results["documents"][0] if results["documents"] else [],
            "metadatas": results["metadatas"][0] if results["metadatas"] else [],
            "distances": results["distances"][0] if results["distances"] else [],
            "ids": results["ids"][0] if results["ids"] else []
        }
    
    def delete_collection(self) -> None:
        """Delete the collection."""
        try:
            self.client.delete_collection(self.collection_name)
            self.collection = None
        except Exception:
            pass
    
    def count(self) -> int:
        """Get the number of documents in the collection."""
        if self.collection is None:
            self.get_or_create_collection()
        return self.collection.count()
    
    def is_empty(self) -> bool:
        """Check if the collection is empty."""
        return self.count() == 0


def initialize_vector_store(persist_directory: str = "./data/vectordb") -> VectorStore:
    """
    Initialize and populate the vector store with clinic FAQs.
    
    Args:
        persist_directory: Directory to persist the database
        
    Returns:
        Initialized VectorStore instance
    """
    store = VectorStore(persist_directory)
    store.get_or_create_collection()
    
    # Check if already populated
    if not store.is_empty():
        return store
    
    # Load clinic info
    data_dir = Path(__file__).parent.parent.parent / "data"
    clinic_info_path = data_dir / "clinic_info.json"
    
    with open(clinic_info_path, "r") as f:
        clinic_data = json.load(f)
    
    documents = []
    metadatas = []
    ids = []
    
    # Add FAQs
    for idx, faq in enumerate(clinic_data.get("faqs", [])):
        # Create a rich document combining question and answer
        doc_text = f"Question: {faq['question']}\nAnswer: {faq['answer']}"
        documents.append(doc_text)
        metadatas.append({
            "category": faq.get("category", "General"),
            "question": faq["question"],
            "answer": faq["answer"],
            "type": "faq"
        })
        ids.append(f"faq-{idx}")
    
    # Add structured clinic information as additional documents
    clinic = clinic_data.get("clinic", {})
    location = clinic_data.get("location", {})
    hours = clinic_data.get("hours", {})
    insurance = clinic_data.get("insurance", {})
    policies = clinic_data.get("policies", {})
    
    # Clinic info document
    clinic_doc = f"""
    Clinic Name: {clinic.get('name', '')}
    Phone: {clinic.get('phone', '')}
    Email: {clinic.get('email', '')}
    Address: {location.get('address', '')}, {location.get('city', '')}, {location.get('state', '')} {location.get('zip', '')}
    Directions: {location.get('directions', '')}
    Parking: {location.get('parking', '')}
    """
    documents.append(clinic_doc)
    metadatas.append({"category": "Clinic Info", "type": "structured"})
    ids.append("clinic-info")
    
    # Hours document
    hours_doc = "Clinic Hours:\n"
    for day, times in hours.items():
        if times.get("closed"):
            hours_doc += f"{day.capitalize()}: Closed\n"
        elif times.get("open"):
            hours_doc += f"{day.capitalize()}: {times['open']} - {times['close']}\n"
    documents.append(hours_doc)
    metadatas.append({"category": "Hours", "type": "structured"})
    ids.append("clinic-hours")
    
    # Insurance document
    insurance_doc = f"""
    Accepted Insurance Providers: {', '.join(insurance.get('accepted_providers', []))}
    Payment Methods: {', '.join(insurance.get('payment_methods', []))}
    Billing Policy: {insurance.get('billing_policy', '')}
    """
    documents.append(insurance_doc)
    metadatas.append({"category": "Insurance", "type": "structured"})
    ids.append("insurance-info")
    
    # Cancellation policy document
    cancel = policies.get("cancellation", {})
    cancel_doc = f"""
    Cancellation Policy:
    Notice Required: {cancel.get('notice_required', '')}
    No-Show Fee: {cancel.get('fee', '')}
    Details: {cancel.get('description', '')}
    """
    documents.append(cancel_doc)
    metadatas.append({"category": "Cancellation", "type": "structured"})
    ids.append("cancellation-policy")
    
    # COVID protocols
    covid = policies.get("covid_protocols", {})
    covid_doc = f"""
    COVID-19 Protocols:
    Current Status: {covid.get('current_status', '')}
    Requirements: {', '.join(covid.get('requirements', []))}
    """
    documents.append(covid_doc)
    metadatas.append({"category": "COVID", "type": "structured"})
    ids.append("covid-protocols")
    
    # Visit preparation
    visit_prep = clinic_data.get("visit_preparation", {})
    first_visit = visit_prep.get("first_visit", {})
    prep_doc = f"""
    First Visit Preparation:
    Required Documents: {', '.join(first_visit.get('documents', []))}
    Recommendations: {', '.join(first_visit.get('recommendations', []))}
    """
    documents.append(prep_doc)
    metadatas.append({"category": "Preparation", "type": "structured"})
    ids.append("visit-preparation")
    
    # Add all documents to the store
    store.add_documents(documents, metadatas, ids)
    
    return store
