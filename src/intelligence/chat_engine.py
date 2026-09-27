"""Conversational AI engine using Ollama."""

import json
import os
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


def _ollama_supports_think() -> bool:
    """Whether the installed ollama client accepts the ``think`` kwarg.

    ``requirements.txt`` pins ``ollama==0.1.7`` (which does not); newer clients
    do. Passing it unconditionally raises ``TypeError`` and silently disables
    retrieval-augmented chat, so it must be probed.
    """
    if not OLLAMA_AVAILABLE:
        return False
    try:
        import inspect

        return "think" in inspect.signature(ollama.chat).parameters
    except (TypeError, ValueError):
        return False


def _llm_num_ctx() -> int:
    """Context window for chat generation (locked M010 profile: 4096 default)."""
    try:
        return max(512, int(os.environ.get("PIS_LLM_NUM_CTX", "4096")))
    except ValueError:
        return 4096


def _llm_num_predict() -> int:
    """Maximum generated tokens (bounds latency for large models)."""
    try:
        return max(32, int(os.environ.get("PIS_LLM_MAX_TOKENS", "384")))
    except ValueError:
        return 384


class ChatEngine:
    """Conversational AI engine for document interaction."""
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        db: Optional[DatabaseManager] = None
    ):
        from ..core.ai_config import model_for
        from ..ai.providers.service import get_ai_service

        self.db = db or DatabaseManager()
        self.semantic_search = SemanticSearchEngine(self.db)
        self._service = get_ai_service()
        self._model_override = model_name
        self._llm = self._service.llm(content_level="text", model_override=model_name)
        info = self._llm.model_info()
        self.model_name = model_name or info.model or model_for("interactive_chat")

        # Conversation history
        self.conversation_history = []

        # Always keep a deterministic fallback; it is used when no provider is
        # available or when a configured provider fails at call time (for
        # example a model that is not installed).
        self.simple_fallback = SimpleChatEngine(self.db)
        if not self._llm.is_available():
            logger.info("No LLM provider available - SimpleChatEngine will answer")
        
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
        
    def is_available(self) -> bool:
        """Check if conversational AI is available."""
        # Always return True since we have SimpleChatEngine as fallback
        return True

    def _select_llm_for_content(self):
        """Pick an LLM provider and whether document body text may be sent.

        Local providers may always receive content. Remote providers receive body
        text only when the remote-content policy allows it; otherwise a
        metadata-only remote selection is used (filenames/paths only).
        """
        policy = self._service.config.content_policy
        llm = self._service.llm(content_level="text", model_override=self._model_override)
        if llm.is_available() and not (llm.remote and not policy.allows_extracted_text):
            return llm, True
        return self._service.llm(content_level="metadata", model_override=self._model_override), False

    def get_model_status(self) -> Dict[str, Any]:
        """Compact provider status for the UI/diagnostics (never exposes keys)."""
        try:
            status = self._service.status()
            llm = status.get("llm", {})
            cfg = status.get("config", {})
            return {
                # Back-compat keys used by the dashboard.
                "available": bool(llm.get("available")),
                "current_model": llm.get("model"),
                # Rich diagnostics.
                "provider": llm.get("provider"),
                "remote": llm.get("remote"),
                "mode": cfg.get("mode"),
                "content_policy": cfg.get("content_policy"),
                "hardware_tier": status.get("hardware_tier"),
                "embeddings": status.get("embeddings"),
                "config": cfg,
                "usage": status.get("usage"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "current_model": None, "error": str(exc)}
    
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
            raw = models.get("models", []) if isinstance(models, dict) else getattr(models, "models", [])
            available_models = []
            for model in raw:
                if isinstance(model, dict):
                    name = model.get("model") or model.get("name")
                else:
                    name = getattr(model, "model", None) or getattr(model, "name", None)
                if name:
                    available_models.append(name)
            
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
    @timeout_operation(float(os.environ.get("PIS_LLM_CHAT_TIMEOUT", "90")))  # large local models need headroom
    def chat(self, user_message: str, search_context: bool = True) -> Dict[str, Any]:
        """Have a conversation with the AI about documents."""
        
        start_time = time.time()
        
        try:
            llm, include_content = self._select_llm_for_content()
            if not llm.is_available():
                if self.simple_fallback:
                    return self.simple_fallback.chat(user_message, search_context)
                return {
                    "response": "No AI provider is available for the current mode and policy.",
                    "error": "provider_unavailable",
                    "sources": [],
                }

            # Search for relevant documents if requested
            context_documents = []
            if search_context:
                context_documents = self._search_relevant_documents(user_message)

            # Build conversation context. Body text is only included when the
            # selected provider is allowed to receive it (local always; remote
            # only per the remote-content policy).
            conversation_context = self._build_context(
                user_message, context_documents, include_content=include_content
            )

            messages = [
                {"role": "system", "content": self.system_prompt},
                *self.conversation_history,
                {"role": "user", "content": conversation_context},
            ]
            result = llm.chat(messages, options={
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": _llm_num_predict(),
                "num_ctx": _llm_num_ctx(),
            })
            ai_response = result.text
            
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
                "model": result.model,
                "provider": result.provider,
                "context_used": len(context_documents) > 0
            }
        
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            # Provider failure (e.g. missing model, outage): degrade to the
            # deterministic fallback rather than surfacing a provider error.
            if self.simple_fallback is not None:
                return self.simple_fallback.chat(user_message, search_context)
            return {
                "response": "The AI provider is currently unavailable.",
                "error": "provider_unavailable",
                "sources": [],
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
        documents: List[Dict[str, Any]],
        include_content: bool = True,
    ) -> str:
        """Build context for the AI including relevant documents.

        ``include_content`` gates extracted body text: when False (e.g. a
        remote provider under a metadata-only policy) only filenames/paths and
        metadata are included.
        """
        
        context = f"User question: {user_message}\n\n"
        
        if documents:
            context += "Relevant documents from the user's collection:\n\n"
            
            for i, doc in enumerate(documents, 1):
                context += f"Document {i}:\n"
                context += f"- Filename: {doc.get('filename', 'Unknown')}\n"
                context += f"- Path: {doc.get('path', 'Unknown')}\n"
                context += f"- Type: {doc.get('file_type', 'unknown')}\n"
                context += f"- Size: {doc.get('size_bytes', 0) / (1024*1024):.2f} MB\n"
                
                if include_content and doc.get('content_text'):
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