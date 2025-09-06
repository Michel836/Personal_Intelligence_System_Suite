"""ChatEngine using Hugging Face Transformers."""

import time
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
    import torch
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False

from ..core.database import DatabaseManager
from .semantic_search import SemanticSearchEngine


class HuggingFaceChatEngine:
    """Chat engine using Hugging Face Transformers."""
    
    def __init__(
        self,
        model_name: str = "microsoft/DialoGPT-medium",
        db: Optional[DatabaseManager] = None
    ):
        self.model_name = model_name
        self.db = db or DatabaseManager()
        self.semantic_search = SemanticSearchEngine(self.db)
        
        # Initialize model if available
        self.model = None
        self.tokenizer = None
        self.chat_pipeline = None
        
        if HF_AVAILABLE:
            self._load_model()
        
        # Conversation history
        self.conversation_history = []
    
    def _load_model(self):
        """Load the Hugging Face model."""
        try:
            print(f"Loading model: {self.model_name}")
            
            # For dialogue models
            if "DialoGPT" in self.model_name:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForCausalLM.from_pretrained(self.model_name)
                # Add padding token if not present
                if self.tokenizer.pad_token is None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
            else:
                # For general text generation
                self.chat_pipeline = pipeline(
                    "text-generation",
                    model=self.model_name,
                    tokenizer=self.model_name,
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                    device_map="auto" if torch.cuda.is_available() else None
                )
            
            print("Model loaded successfully!")
            
        except Exception as e:
            print(f"Error loading model: {e}")
            print("Falling back to simple responses...")
    
    def is_available(self) -> bool:
        """Check if Hugging Face chat is available."""
        return HF_AVAILABLE and (self.model is not None or self.chat_pipeline is not None)
    
    def chat(self, user_message: str, search_context: bool = True) -> Dict[str, Any]:
        """Have a conversation using Hugging Face model."""
        
        if not self.is_available():
            return {
                "response": "Hugging Face models not available. Install with: pip install transformers torch",
                "error": "Transformers not available",
                "sources": []
            }
        
        start_time = time.time()
        
        try:
            # Search for relevant documents if requested
            context_documents = []
            if search_context:
                context_documents = self._search_relevant_documents(user_message)
            
            # Build conversation context
            full_context = self._build_context(user_message, context_documents)
            
            # Generate response
            if self.chat_pipeline:
                response_text = self._generate_with_pipeline(full_context)
            else:
                response_text = self._generate_with_model(full_context)
            
            # Update conversation history
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": response_text})
            
            # Keep conversation history reasonable length
            if len(self.conversation_history) > 10:
                self.conversation_history = self.conversation_history[-10:]
            
            response_time = time.time() - start_time
            
            return {
                "response": response_text,
                "sources": context_documents,
                "response_time": response_time,
                "model": self.model_name,
                "context_used": len(context_documents) > 0
            }
        
        except Exception as e:
            return {
                "response": f"Désolé, j'ai rencontré une erreur : {str(e)}",
                "error": str(e),
                "sources": []
            }
    
    def _generate_with_pipeline(self, context: str) -> str:
        """Generate response using text-generation pipeline."""
        try:
            # Add instruction for better responses
            prompt = f"""Vous êtes un assistant pour explorer des documents. Répondez de manière concise et utile.

Question: {context}

Réponse:"""
            
            outputs = self.chat_pipeline(
                prompt,
                max_new_tokens=200,
                temperature=0.7,
                do_sample=True,
                pad_token_id=self.chat_pipeline.tokenizer.eos_token_id
            )
            
            response = outputs[0]['generated_text']
            # Extract only the new part after "Réponse:"
            if "Réponse:" in response:
                response = response.split("Réponse:")[-1].strip()
            else:
                # Fallback: take text after the prompt
                response = response[len(prompt):].strip()
            
            return response if response else "Je peux vous aider à explorer vos documents. Que recherchez-vous ?"
            
        except Exception as e:
            print(f"Pipeline generation error: {e}")
            return "Je rencontre des difficultés techniques. Comment puis-je vous aider autrement ?"
    
    def _generate_with_model(self, context: str) -> str:
        """Generate response using DialoGPT model."""
        try:
            # Encode the context
            inputs = self.tokenizer.encode(context + self.tokenizer.eos_token, return_tensors='pt')
            
            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs,
                    max_length=inputs.shape[1] + 100,
                    temperature=0.7,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode response
            response = self.tokenizer.decode(outputs[:, inputs.shape[1]:][0], skip_special_tokens=True)
            
            return response if response else "Comment puis-je vous aider avec vos documents ?"
            
        except Exception as e:
            print(f"Model generation error: {e}")
            return "Je peux vous aider à rechercher dans vos documents. Que cherchez-vous ?"
    
    def _search_relevant_documents(
        self, 
        query: str, 
        max_docs: int = 3  # Reduced for local models
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
        """Build context for the model including relevant documents."""
        
        context = f"{user_message}"
        
        if documents:
            context += "\n\nDocuments trouvés :"
            
            for i, doc in enumerate(documents, 1):
                context += f"\n{i}. {doc.get('filename', 'Fichier')}"
                
                if doc.get('content_text'):
                    # Include a brief excerpt for local models
                    content = doc['content_text'][:200]
                    if len(doc['content_text']) > 200:
                        content += "..."
                    context += f" - {content}"
        
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
        
        # Build specific context for this document (keep it short for local models)
        context = f"Question sur {doc_dict['filename']}: {question}"
        
        if doc_dict.get('content_text'):
            # Include first 300 characters of content
            content = doc_dict['content_text'][:300]
            if len(doc_dict['content_text']) > 300:
                content += "..."
            context += f"\nContenu: {content}"
        
        return self.chat(context, search_context=False)
    
    def summarize_documents(self, file_type: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
        """Generate a summary of documents in the collection."""
        
        # Get documents to summarize (reduced limit for local models)
        if file_type and file_type != 'all':
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
        
        # Build summary request (keep it concise)
        context = f"Résumez ces {len(documents)} fichiers:\n"
        
        for i, doc in enumerate(documents, 1):
            context += f"{i}. {doc['filename']} ({doc['file_type']})\n"
        
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
            "transformers_available": HF_AVAILABLE,
            "backend": "Hugging Face Transformers"
        }