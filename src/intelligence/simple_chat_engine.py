"""Simple chat engine that works without Ollama - uses rule-based responses."""

import time
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..core.database import DatabaseManager
from .semantic_search import SemanticSearchEngine


class SimpleChatEngine:
    """Simplified chat engine that works without external LLM."""
    
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.semantic_search = SemanticSearchEngine(self.db)
        self.conversation_history = []
    
    def is_available(self) -> bool:
        """Always available since no external dependencies."""
        return True
    
    def chat(self, user_message: str, search_context: bool = True) -> Dict[str, Any]:
        """Process chat with rule-based responses and document search."""
        
        start_time = time.time()
        message_lower = user_message.lower()
        
        # Search for documents if requested
        context_documents = []
        if search_context:
            # Extract search terms
            search_terms = self._extract_search_terms(user_message)
            if search_terms:
                context_documents = self._search_documents(search_terms)
        
        # Generate appropriate response
        response = self._generate_response(user_message, context_documents)
        
        # Update conversation history
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": response})
        
        # Keep history reasonable length
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
        
        response_time = time.time() - start_time
        
        return {
            "response": response,
            "sources": context_documents,
            "response_time": response_time,
            "model": "Simple Rule-Based (No LLM)",
            "context_used": len(context_documents) > 0
        }
    
    def _extract_search_terms(self, message: str) -> str:
        """Extract search terms from user message."""
        
        # Keywords that indicate search intent
        search_indicators = [
            'trouve', 'cherche', 'recherche', 'find', 'search', 'look for',
            'montre', 'show', 'display', 'affiche', 'liste', 'list',
            'où', 'where', 'quel', 'which', 'what', 'qui', 'who'
        ]
        
        message_lower = message.lower()
        
        # Check for search intent
        has_search_intent = any(indicator in message_lower for indicator in search_indicators)
        
        if has_search_intent or 'michel' in message_lower:
            # Extract quoted terms
            import re
            quoted = re.findall(r'"([^"]*)"', message)
            if quoted:
                return ' '.join(quoted)
            
            # Extract key terms (remove common words)
            stop_words = {
                'le', 'la', 'les', 'un', 'une', 'des', 'de', 'du',
                'et', 'ou', 'mais', 'donc', 'or', 'ni', 'car',
                'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on',
                'trouve', 'cherche', 'montre', 'affiche', 'find', 'search',
                'moi', 'me', 'je', 'tu', 'il', 'elle', 'nous', 'vous',
                'document', 'fichier', 'file', 'docs'
            }
            
            words = message_lower.split()
            keywords = [w for w in words if w not in stop_words and len(w) > 2]
            
            if keywords:
                return ' '.join(keywords[:3])  # Limit to 3 keywords
        
        return ""
    
    def _search_documents(self, query: str) -> List[Dict[str, Any]]:
        """Search for relevant documents."""
        
        results = []
        
        # Try semantic search first if available
        if self.semantic_search.is_available():
            results = self.semantic_search.semantic_search(
                query, 
                limit=5, 
                similarity_threshold=0.2
            )
        
        # Fallback to regular search
        if not results:
            results = self.db.search_files(query=query, limit=5)
        
        return results
    
    def _generate_response(self, message: str, documents: List[Dict[str, Any]]) -> str:
        """Generate a response based on message and found documents."""
        
        message_lower = message.lower()
        
        # Greeting responses
        if any(word in message_lower for word in ['bonjour', 'salut', 'hello', 'hi']):
            return "Bonjour ! Je suis votre assistant pour explorer vos 36TB de documents. Comment puis-je vous aider ?"
        
        # Help responses
        if any(word in message_lower for word in ['aide', 'help', 'comment', 'how']):
            return """Je peux vous aider à :
• Rechercher des documents spécifiques (ex: "trouve michel")
• Explorer vos fichiers par type (ex: "montre les PDF")
• Analyser le contenu de vos documents
• Obtenir des statistiques sur votre collection

Que souhaitez-vous faire ?"""
        
        # Document search responses
        if documents:
            response = f"J'ai trouvé {len(documents)} document(s) pertinent(s) :\n\n"
            
            for i, doc in enumerate(documents, 1):
                response += f"{i}. **{doc.get('filename', 'Sans nom')}**\n"
                response += f"   📁 {doc.get('path', 'Chemin inconnu')}\n"
                
                # Add content preview if available
                if doc.get('content_text'):
                    preview = doc['content_text'][:150]
                    if len(doc['content_text']) > 150:
                        preview += "..."
                    response += f"   📄 *{preview}*\n"
                
                # Add relevance score if available
                if 'semantic_similarity' in doc:
                    response += f"   🎯 Pertinence: {doc['semantic_similarity']:.2%}\n"
                
                response += "\n"
            
            # Add search-specific guidance
            if 'michel' in message_lower:
                response += "💡 J'ai recherché 'michel' dans vos documents. Utilisez la page 'Search' pour affiner avec des filtres."
            
            return response
        
        # No documents found
        if any(word in message_lower for word in ['trouve', 'cherche', 'find', 'search', 'michel']):
            suggestions = []
            
            if 'michel' in message_lower:
                suggestions = [
                    "Vérifiez l'orthographe exacte",
                    "Essayez 'Michele' ou 'Michael'",
                    "Lancez d'abord l'extraction de contenu : python scripts/extract_content.py"
                ]
            
            response = "Je n'ai pas trouvé de documents correspondants.\n\n"
            if suggestions:
                response += "💡 Suggestions :\n"
                for sugg in suggestions:
                    response += f"• {sugg}\n"
            else:
                response += "Essayez avec d'autres termes de recherche ou vérifiez que les contenus ont été extraits."
            
            return response
        
        # Statistics request
        if any(word in message_lower for word in ['statistique', 'stats', 'combien', 'nombre']):
            stats = self.db.get_statistics()
            return f"""📊 Statistiques de votre collection :
• Total de fichiers : {stats['total_files']:,}
• Taille totale : {stats['total_gb']:.2f} GB
• Types de fichiers : {len(stats.get('by_type', {}))} différents

Utilisez la page 'Statistics' pour plus de détails."""
        
        # Default response
        return """Je suis votre assistant pour explorer vos 36TB de données.
        
Essayez des commandes comme :
• "Trouve les documents qui mentionnent michel"
• "Cherche les fichiers PDF"
• "Montre les statistiques"
• "Aide"

Que recherchez-vous ?"""
    
    def ask_about_document(self, document_id: int, question: str) -> Dict[str, Any]:
        """Answer a question about a specific document."""
        
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
        
        # Generate response about the document
        response = f"📄 **{doc_dict['filename']}**\n\n"
        response += f"• Type : {doc_dict.get('file_type', 'inconnu')}\n"
        response += f"• Taille : {doc_dict['size_bytes'] / (1024*1024):.2f} MB\n"
        response += f"• Chemin : {doc_dict['path']}\n"
        
        if doc_dict.get('content_text'):
            response += f"\n📝 Contenu (extrait) :\n{doc_dict['content_text'][:500]}..."
        else:
            response += "\n⚠️ Contenu non extrait. Lancez l'extraction pour analyser ce document."
        
        return {
            "response": response,
            "sources": [doc_dict]
        }
    
    def summarize_documents(self, file_type: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Generate a summary of documents."""
        
        # Get documents
        from ..scanner.models import FileType
        
        if file_type and file_type != 'all':
            documents = self.db.search_files(
                file_type=FileType(file_type),
                limit=limit
            )
        else:
            documents = self.db.search_files(limit=limit)
        
        if not documents:
            return {
                "response": "Aucun document trouvé.",
                "sources": []
            }
        
        # Generate summary
        response = f"📊 **Résumé de {len(documents)} documents**\n\n"
        
        # Group by type
        by_type = {}
        total_size = 0
        for doc in documents:
            doc_type = doc.get('file_type', 'other')
            if doc_type not in by_type:
                by_type[doc_type] = []
            by_type[doc_type].append(doc)
            total_size += doc.get('size_bytes', 0)
        
        response += f"**Vue d'ensemble :**\n"
        response += f"• Nombre total : {len(documents)} fichiers\n"
        response += f"• Taille totale : {total_size / (1024*1024*1024):.2f} GB\n"
        response += f"• Types : {', '.join(by_type.keys())}\n\n"
        
        response += "**Par type :**\n"
        for doc_type, docs in by_type.items():
            response += f"• {doc_type} : {len(docs)} fichiers\n"
        
        response += "\n**Fichiers récents :**\n"
        for doc in documents[:5]:
            response += f"• {doc['filename']}\n"
        
        return {
            "response": response,
            "sources": documents
        }
    
    def clear_conversation(self):
        """Clear conversation history."""
        self.conversation_history = []
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get conversation history."""
        return self.conversation_history.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get chat engine statistics."""
        return {
            "available": True,
            "model": "Simple Rule-Based (No LLM)",
            "conversation_length": len(self.conversation_history),
            "semantic_search_available": self.semantic_search.is_available(),
            "ollama_installed": False,
            "mode": "Offline - No external dependencies"
        }