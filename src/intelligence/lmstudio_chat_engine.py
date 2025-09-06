"""ChatEngine using LM Studio as LLM backend."""

import time
import requests
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..core.database import DatabaseManager
from .semantic_search import SemanticSearchEngine


class LMStudioChatEngine:
    """Chat engine using LM Studio local LLM server."""
    
    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model_name: str = "local-model",
        db: Optional[DatabaseManager] = None
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.db = db or DatabaseManager()
        self.semantic_search = SemanticSearchEngine(self.db)
        
        # Conversation history
        self.conversation_history = []
        
        # System prompt
        self.system_prompt = """Vous êtes un assistant intelligent pour un système de gestion de documents personnels appelé "36TB Intelligence".

Vous aidez les utilisateurs à trouver et comprendre les informations dans leur collection de 36TB de documents personnels, fichiers et données de 2010 à aujourd'hui.

Vos capacités :
- Rechercher dans les documents avec recherche textuelle et sémantique
- Analyser le contenu et les métadonnées des documents
- Fournir des résumés et des insights
- Répondre aux questions sur les fichiers et leur contenu
- Aider à organiser et comprendre les grandes collections de documents

Directives :
- Soyez utile, concis et précis
- Lors de la recherche de documents, fournissez des noms de fichiers spécifiques et des extraits pertinents
- Si vous ne trouvez pas d'information, suggérez des termes de recherche alternatifs
- Citez toujours les documents sources lors de la fourniture d'informations
- Utilisez le français quand l'utilisateur parle français, sinon l'anglais"""
    
    def is_available(self) -> bool:
        """Check if LM Studio server is available."""
        try:
            response = requests.get(f"{self.base_url}/models", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def chat(self, user_message: str, search_context: bool = True) -> Dict[str, Any]:
        """Have a conversation with the LM Studio LLM."""
        
        if not self.is_available():
            return {
                "response": "LM Studio server not available. Please start LM Studio and load a model.",
                "error": "LM Studio not available",
                "sources": []
            }
        
        start_time = time.time()
        
        try:
            # Search for relevant documents if requested
            context_documents = []
            if search_context:
                context_documents = self._search_relevant_documents(user_message)
            
            # Build conversation context
            conversation_context = self._build_context(user_message, context_documents)
            
            # Prepare messages for LM Studio
            messages = [
                {"role": "system", "content": self.system_prompt},
                *self.conversation_history,
                {"role": "user", "content": conversation_context}
            ]
            
            # Call LM Studio API
            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000,
                "stream": False
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=60
            )
            
            if response.status_code != 200:
                raise Exception(f"LM Studio API error: {response.status_code} - {response.text}")
            
            result = response.json()
            ai_response = result['choices'][0]['message']['content']
            
            # Update conversation history
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": ai_response})
            
            # Keep conversation history reasonable length
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-20:]
            
            response_time = time.time() - start_time
            
            return {
                "response": ai_response,
                "sources": context_documents,
                "response_time": response_time,
                "model": self.model_name,
                "context_used": len(context_documents) > 0
            }
        
        except Exception as e:
            return {
                "response": f"Sorry, I encountered an error: {str(e)}",
                "error": str(e),
                "sources": []
            }
    
    def _search_relevant_documents(
        self, 
        query: str, 
        max_docs: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for documents relevant to the query."""
        
        try:
            # Try semantic search first
            if self.semantic_search.is_available():
                results = self.semantic_search.semantic_search(
                    query,
                    limit=max_docs,
                    similarity_threshold=0.3
                )
                
                if results:
                    return results
            
            # Fallback to regular search
            results = self.db.search_files(query=query, limit=max_docs)
            return results
        
        except Exception as e:
            print(f"Error searching documents: {e}")
            return []
    
    def _build_context(
        self, 
        user_message: str, 
        documents: List[Dict[str, Any]]
    ) -> str:
        """Build context for the LLM including relevant documents."""
        
        context = f"Question de l'utilisateur : {user_message}\n\n"
        
        if documents:
            context += "Documents pertinents de la collection de l'utilisateur :\n\n"
            
            for i, doc in enumerate(documents, 1):
                context += f"Document {i} :\n"
                context += f"- Nom du fichier : {doc.get('filename', 'Inconnu')}\n"
                context += f"- Chemin : {doc.get('path', 'Inconnu')}\n"
                context += f"- Type : {doc.get('file_type', 'inconnu')}\n"
                context += f"- Taille : {doc.get('size_bytes', 0) / (1024*1024):.2f} MB\n"
                
                if doc.get('content_text'):
                    # Include a relevant excerpt
                    content = doc['content_text']
                    if len(content) > 500:
                        content = content[:500] + "..."
                    context += f"- Extrait du contenu : {content}\n"
                
                if 'semantic_similarity' in doc:
                    context += f"- Pertinence : {doc['semantic_similarity']:.3f}\n"
                
                context += "\n"
            
            context += "Basé sur ces documents, veuillez répondre à la question de l'utilisateur.\n"
            context += "Mentionnez toujours les noms de fichiers spécifiques lors du référencement d'informations.\n\n"
        else:
            context += "Aucun document spécifique trouvé. Fournissez des conseils généraux ou suggérez des termes de recherche.\n\n"
        
        return context
    
    def ask_about_document(self, document_id: int, question: str) -> Dict[str, Any]:
        """Ask a specific question about a particular document."""
        
        # Get the document
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM files WHERE id = ?", (document_id,))
            doc = cursor.fetchone()
            
            if not doc:
                return {
                    "response": "Document non trouvé.",
                    "error": "Document not found",
                    "sources": []
                }
        
        doc_dict = dict(doc)
        
        # Build specific context for this document
        context = f"Question sur le document '{doc_dict['filename']}' : {question}\n\n"
        context += f"Détails du document :\n"
        context += f"- Nom du fichier : {doc_dict['filename']}\n"
        context += f"- Chemin : {doc_dict['path']}\n"
        context += f"- Type : {doc_dict['file_type']}\n"
        context += f"- Taille : {doc_dict['size_bytes'] / (1024*1024):.2f} MB\n"
        
        if doc_dict.get('content_text'):
            context += f"- Contenu complet :\n{doc_dict['content_text']}\n"
        
        context += f"\nVeuillez répondre à la question basée sur ce document."
        
        return self.chat(context, search_context=False)
    
    def summarize_documents(self, file_type: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Generate a summary of documents in the collection."""
        
        # Get documents to summarize
        if file_type:
            from ..scanner.models import FileType
            documents = self.db.search_files(
                file_type=FileType(file_type),
                limit=limit
            )
        else:
            documents = self.db.search_files(limit=limit)
        
        if not documents:
            return {
                "response": "Aucun document trouvé à résumer.",
                "sources": []
            }
        
        # Build summary request
        context = f"Veuillez fournir un résumé de ces {len(documents)} documents :\n\n"
        
        for i, doc in enumerate(documents, 1):
            context += f"{i}. {doc['filename']}\n"
            context += f"   Type : {doc['file_type']}\n"
            context += f"   Taille : {doc['size_bytes'] / (1024*1024):.2f} MB\n"
            
            if doc.get('content_text'):
                # Include brief content
                content = doc['content_text'][:200] + "..." if len(doc['content_text']) > 200 else doc['content_text']
                context += f"   Contenu : {content}\n"
            
            context += "\n"
        
        context += "Fournissez un résumé organisé en se concentrant sur :\n"
        context += "- Les principaux sujets et thèmes\n"
        context += "- Les types de documents et leurs objectifs\n"
        context += "- Tout modèle ou insight notable\n"
        
        return self.chat(context, search_context=False)
    
    def clear_conversation(self):
        """Clear conversation history."""
        self.conversation_history = []
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get current conversation history."""
        return self.conversation_history.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get chat engine statistics."""
        return {
            "available": self.is_available(),
            "model": self.model_name,
            "conversation_length": len(self.conversation_history),
            "semantic_search_available": self.semantic_search.is_available(),
            "lm_studio_connected": self.is_available(),
            "backend": "LM Studio Local Server"
        }