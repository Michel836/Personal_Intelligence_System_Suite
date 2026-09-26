"""Conversational AI engine using Ollama."""

import json
import time
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from loguru import logger
from ..core.error_handling import safe_ai_operation, timeout_operation

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("ollama package not available - conversational AI disabled")

from ..core.database import DatabaseManager
from .semantic_search import SemanticSearchEngine
from .simple_chat_engine import SimpleChatEngine


class ChatEngine:
    """Conversational AI engine for document interaction."""
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        db: Optional[DatabaseManager] = None
    ):
        from ..core.ai_config import model_for
        self.model_name = model_name or model_for("interactive_chat")
        self.db = db or DatabaseManager()
        self.semantic_search = SemanticSearchEngine(self.db)
        
        # Conversation history
        self.conversation_history = []
        
        # Fallback to simple chat if Ollama not available
        self.simple_fallback = None
        if not OLLAMA_AVAILABLE or not self._test_ollama_connection():
            logger.info("Using SimpleChatEngine as fallback")
            self.simple_fallback = SimpleChatEngine(self.db)
        
        # System prompt
        self.system_prompt = """You are an intelligent assistant for a personal document management system called "36TB Intelligence". 

You help users find and understand information from their 36TB collection of personal documents, files, and data spanning from 2010 to present.

Your capabilities:
- Search through documents using both keyword and semantic search
- Analyze document content and metadata
- Provide summaries and insights
- Answer questions about files and their contents
- Help organize and understand large document collections

Guidelines:
- Be helpful, concise, and accurate
- When searching documents, provide specific file names and relevant excerpts
- If you can't find information, suggest alternative search terms
- Always cite the source documents when providing information
- Use French when the user speaks French, English otherwise
"""
        
        if OLLAMA_AVAILABLE:
            self._check_model_availability()
        else:
            logger.error("Ollama not available. Install with: pip install ollama")
    
    def is_available(self) -> bool:
        """Check if conversational AI is available."""
        # Always return True since we have SimpleChatEngine as fallback
        return True
    
    def _test_ollama_connection(self) -> bool:
        """Test if Ollama is actually accessible."""
        if not OLLAMA_AVAILABLE:
            return False
        
        try:
            # Test with timeout
            response = ollama.list()
            return True
        except Exception as e:
            logger.debug(f"Ollama connection test failed: {e}")
            return False
    
    def _check_model_availability(self) -> bool:
        """Check if the specified model is available."""
        try:
            # Get models with timeout handling
            models = ollama.list()
            available_models = [model.model for model in models.models]
            
            if self.model_name in available_models:
                logger.info(f"Model {self.model_name} is available")
                return True
            else:
                logger.warning(f"Model {self.model_name} not found. Available models: {available_models}")
                # Try to use a fallback model
                fallback_models = ["llama3.2:latest", "llama3.1:latest", "llama2:latest", "mistral:latest"]
                for fallback in fallback_models:
                    if fallback in available_models:
                        logger.info(f"Using fallback model: {fallback}")
                        self.model_name = fallback
                        return True
                
                logger.error("No compatible models found")
                return False
        
        except Exception as e:
            logger.error(f"Error checking Ollama models: {e}")
            return False
    
    @safe_ai_operation
    @timeout_operation(45.0)  # 45 second timeout for chat operations
    def chat(self, user_message: str, search_context: bool = True) -> Dict[str, Any]:
        """Have a conversation with the AI about documents."""
        
        # Use simple fallback if Ollama not available
        if self.simple_fallback:
            return self.simple_fallback.chat(user_message, search_context)
        
        start_time = time.time()
        
        try:
            # Search for relevant documents if requested
            context_documents = []
            if search_context:
                context_documents = self._search_relevant_documents(user_message)
            
            # Build conversation context
            conversation_context = self._build_context(user_message, context_documents)
            
            # Generate AI response with timeout
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    *self.conversation_history,
                    {"role": "user", "content": conversation_context}
                ],
                options={
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 1000,
                    "timeout": 30.0  # 30 second timeout
                }
            )
            
            ai_response = response['message']['content']
            
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
            logger.error(f"Error in chat: {e}")
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
            logger.error(f"Error searching documents: {e}")
            return []
    
    def _build_context(
        self, 
        user_message: str, 
        documents: List[Dict[str, Any]]
    ) -> str:
        """Build context for the AI including relevant documents."""
        
        context = f"User question: {user_message}\n\n"
        
        if documents:
            context += "Relevant documents from the user's collection:\n\n"
            
            for i, doc in enumerate(documents, 1):
                context += f"Document {i}:\n"
                context += f"- Filename: {doc.get('filename', 'Unknown')}\n"
                context += f"- Path: {doc.get('path', 'Unknown')}\n"
                context += f"- Type: {doc.get('file_type', 'unknown')}\n"
                context += f"- Size: {doc.get('size_bytes', 0) / (1024*1024):.2f} MB\n"
                
                if doc.get('content_text'):
                    # Include a relevant excerpt
                    content = doc['content_text']
                    if len(content) > 500:
                        content = content[:500] + "..."
                    context += f"- Content excerpt: {content}\n"
                
                if 'semantic_similarity' in doc:
                    context += f"- Relevance: {doc['semantic_similarity']:.3f}\n"
                
                context += "\n"
            
            context += "Based on these documents, please answer the user's question.\n"
            context += "Always mention specific filenames when referencing information.\n\n"
        else:
            context += "No specific documents found. Provide general guidance or suggest search terms.\n\n"
        
        return context
    
    def ask_about_document(self, document_id: int, question: str) -> Dict[str, Any]:
        """Ask a specific question about a particular document."""
        
        # Use simple fallback if Ollama not available
        if self.simple_fallback:
            return self.simple_fallback.ask_about_document(document_id, question)
        
        # Get the document
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM files WHERE id = ?", (document_id,))
            doc = cursor.fetchone()
            
            if not doc:
                return {
                    "response": "Document not found.",
                    "error": "Document not found",
                    "sources": []
                }
        
        doc_dict = dict(doc)
        
        # Build specific context for this document
        context = f"Question about document '{doc_dict['filename']}':\n{question}\n\n"
        context += f"Document details:\n"
        context += f"- Filename: {doc_dict['filename']}\n"
        context += f"- Path: {doc_dict['path']}\n"
        context += f"- Type: {doc_dict['file_type']}\n"
        context += f"- Size: {doc_dict['size_bytes'] / (1024*1024):.2f} MB\n"
        
        if doc_dict.get('content_text'):
            context += f"- Full content:\n{doc_dict['content_text']}\n"
        
        context += f"\nPlease answer the question based on this document."
        
        return self.chat(context, search_context=False)
    
    def summarize_documents(self, file_type: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Generate a summary of documents in the collection."""
        
        # Use simple fallback if Ollama not available
        if self.simple_fallback:
            return self.simple_fallback.summarize_documents(file_type, limit)
        
        # Get documents to summarize
        if file_type:
            from .models import FileType
            documents = self.db.search_files(
                file_type=FileType(file_type),
                limit=limit
            )
        else:
            documents = self.db.search_files(limit=limit)
        
        if not documents:
            return {
                "response": "No documents found to summarize.",
                "sources": []
            }
        
        # Build summary request
        context = f"Please provide a summary of these {len(documents)} documents:\n\n"
        
        for i, doc in enumerate(documents, 1):
            context += f"{i}. {doc['filename']}\n"
            context += f"   Type: {doc['file_type']}\n"
            context += f"   Size: {doc['size_bytes'] / (1024*1024):.2f} MB\n"
            
            if doc.get('content_text'):
                # Include brief content
                content = doc['content_text'][:200] + "..." if len(doc['content_text']) > 200 else doc['content_text']
                context += f"   Content: {content}\n"
            
            context += "\n"
        
        context += "Provide an organized summary focusing on:\n"
        context += "- Main topics and themes\n"
        context += "- Document types and purposes\n"
        context += "- Any notable patterns or insights\n"
        
        return self.chat(context, search_context=False)
    
    def clear_conversation(self):
        """Clear conversation history."""
        if self.simple_fallback:
            self.simple_fallback.clear_conversation()
        self.conversation_history = []
        logger.info("Conversation history cleared")
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get current conversation history."""
        if self.simple_fallback:
            return self.simple_fallback.get_conversation_history()
        return self.conversation_history.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get chat engine statistics."""
        if self.simple_fallback:
            return self.simple_fallback.get_stats()
        return {
            "available": self.is_available(),
            "model": self.model_name,
            "conversation_length": len(self.conversation_history),
            "semantic_search_available": self.semantic_search.is_available(),
            "ollama_installed": OLLAMA_AVAILABLE
        }