"""Advanced AI system with document summaries and intelligent analysis."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import hashlib
import re

from loguru import logger

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests not available - some AI features may be limited")


class AdvancedAI:
    """Advanced AI system for document analysis and summaries."""
    
    def __init__(self, db_path=None, ollama_url: str = "http://localhost:11434"):
        from ..core.database import default_db_path
        self.db_path = db_path or default_db_path()
        self.ollama_url = ollama_url
        self.model = "llama3.2:latest"
        self._init_ai_tables()
    
    def _init_ai_tables(self):
        """Initialize AI-related tables."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Summaries table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER UNIQUE,
                    summary_text TEXT NOT NULL,
                    key_points TEXT, -- JSON array of key points
                    topics TEXT, -- JSON array of identified topics
                    sentiment TEXT DEFAULT 'neutral',
                    summary_length INTEGER DEFAULT 0,
                    content_hash TEXT, -- Hash of original content
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    model_used TEXT DEFAULT 'llama3.2',
                    confidence_score REAL DEFAULT 0.0,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
                )
            """)
            
            # Document insights table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS document_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER,
                    insight_type TEXT NOT NULL, -- 'entities', 'keywords', 'concepts', etc.
                    insight_data TEXT NOT NULL, -- JSON data
                    confidence REAL DEFAULT 0.0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
                )
            """)
            
            # Q&A history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS qa_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    context_files TEXT, -- JSON array of file IDs used for context
                    model_used TEXT DEFAULT 'llama3.2',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    rating INTEGER DEFAULT 0, -- User rating 1-5
                    feedback TEXT DEFAULT ''
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_summaries_file_id ON summaries(file_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_insights_file_id ON document_insights(file_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_insights_type ON document_insights(insight_type)")
            
            conn.commit()
            conn.close()
            
            logger.info("Advanced AI tables initialized")
            
        except Exception as e:
            logger.error(f"Error initializing AI tables: {e}")
    
    def is_ollama_available(self) -> bool:
        """Check if Ollama is running and accessible."""
        if not REQUESTS_AVAILABLE:
            return False
        
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def _make_ollama_request(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1000) -> Optional[str]:
        """Make a request to Ollama API."""
        if not self.is_ollama_available():
            return None
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.1,
                    "top_p": 0.9
                }
            }
            
            response = requests.post(f"{self.ollama_url}/api/chat", json=payload, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                return result.get("message", {}).get("content", "").strip()
            else:
                logger.warning(f"Ollama request failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error making Ollama request: {e}")
            return None
    
    # Document Summarization
    def generate_summary(self, file_id: int, force_regenerate: bool = False) -> Optional[Dict[str, Any]]:
        """Generate or retrieve AI summary for a document."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get file info
            cursor.execute("""
                SELECT filename, content_text, file_type 
                FROM files 
                WHERE id = ? AND (content_text IS NOT NULL AND content_text != '')
            """, (file_id,))
            
            file_data = cursor.fetchone()
            if not file_data:
                conn.close()
                return None
            
            filename, content, file_type = file_data
            
            # Calculate content hash
            content_hash = hashlib.md5(content.encode()).hexdigest()
            
            # Check if summary already exists and is current
            if not force_regenerate:
                cursor.execute("""
                    SELECT summary_text, key_points, topics, sentiment, 
                           created_at, confidence_score
                    FROM summaries 
                    WHERE file_id = ? AND content_hash = ?
                """, (file_id, content_hash))
                
                existing = cursor.fetchone()
                if existing:
                    conn.close()
                    return {
                        'summary': existing[0],
                        'key_points': json.loads(existing[1]) if existing[1] else [],
                        'topics': json.loads(existing[2]) if existing[2] else [],
                        'sentiment': existing[3],
                        'created_at': existing[4],
                        'confidence': existing[5],
                        'from_cache': True
                    }
            
            # Generate new summary
            summary_data = self._generate_document_summary(content, filename, file_type)
            
            if not summary_data:
                conn.close()
                return None
            
            # Save summary to database
            cursor.execute("""
                INSERT OR REPLACE INTO summaries 
                (file_id, summary_text, key_points, topics, sentiment, 
                 summary_length, content_hash, model_used, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                file_id,
                summary_data['summary'],
                json.dumps(summary_data['key_points']),
                json.dumps(summary_data['topics']),
                summary_data['sentiment'],
                len(summary_data['summary']),
                content_hash,
                self.model,
                summary_data['confidence']
            ))
            
            conn.commit()
            conn.close()
            
            summary_data['from_cache'] = False
            return summary_data
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return None
    
    def _generate_document_summary(self, content: str, filename: str, file_type: str) -> Optional[Dict[str, Any]]:
        """Use AI to generate document summary and analysis."""
        # Truncate content if too long
        max_content_length = 8000  # Reasonable limit for AI processing
        truncated_content = content[:max_content_length]
        if len(content) > max_content_length:
            truncated_content += "\\n\\n[Content truncated for analysis]"
        
        system_prompt = f"""You are an expert document analyzer. Analyze the provided document and provide a comprehensive summary.
        
        Document type: {file_type}
        Document name: {filename}
        
        Provide your response in this exact JSON format:
        {{
            "summary": "A concise 2-3 paragraph summary of the main content",
            "key_points": ["point 1", "point 2", "point 3"],
            "topics": ["topic1", "topic2", "topic3"],
            "sentiment": "positive/negative/neutral",
            "confidence": 0.85
        }}
        
        Make sure the summary captures the essence of the document, key points are actionable insights, and topics are relevant categories."""
        
        prompt = f"Analyze this document:\\n\\n{truncated_content}"
        
        response = self._make_ollama_request(prompt, system_prompt, max_tokens=1500)
        
        if not response:
            return None
        
        try:
            # Extract JSON from response (handle potential formatting issues)
            json_match = re.search(r'\\{.*\\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                result = json.loads(json_str)
                
                # Validate required fields
                required_fields = ['summary', 'key_points', 'topics', 'sentiment', 'confidence']
                if all(field in result for field in required_fields):
                    return result
                else:
                    logger.warning("AI response missing required fields")
                    
            # Fallback: parse manually if JSON parsing fails
            return self._manual_summary_parsing(response, content)
            
        except json.JSONDecodeError:
            logger.warning("Failed to parse AI JSON response, using manual parsing")
            return self._manual_summary_parsing(response, content)
    
    def _manual_summary_parsing(self, response: str, content: str) -> Dict[str, Any]:
        """Manual parsing fallback for summary generation."""
        # Basic fallback summary
        lines = content.split('\\n')
        first_paragraph = ' '.join(lines[:3])[:300] + "..."
        
        # Extract some basic keywords
        words = re.findall(r'\\b\\w{4,}\\b', content.lower())
        word_freq = {}
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        topics = [word for word, count in top_words if count > 2]
        
        return {
            'summary': first_paragraph,
            'key_points': [f"Document contains {len(lines)} lines of content"],
            'topics': topics[:3],
            'sentiment': 'neutral',
            'confidence': 0.5
        }
    
    def get_summary(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Get existing summary for a file."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.*, f.filename
                FROM summaries s
                JOIN files f ON s.file_id = f.id
                WHERE s.file_id = ?
            """, (file_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    'summary': result['summary_text'],
                    'key_points': json.loads(result['key_points']) if result['key_points'] else [],
                    'topics': json.loads(result['topics']) if result['topics'] else [],
                    'sentiment': result['sentiment'],
                    'created_at': result['created_at'],
                    'confidence': result['confidence_score'],
                    'filename': result['filename']
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting summary: {e}")
            return None
    
    def batch_generate_summaries(self, limit: int = 50, file_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Generate summaries for multiple files in batch."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Build query conditions
            conditions = ["content_text IS NOT NULL", "content_text != ''"]
            params = []
            
            if file_types:
                placeholders = ','.join('?' * len(file_types))
                conditions.append(f"file_type IN ({placeholders})")
                params.extend(file_types)
            
            # Get files without summaries
            query = f"""
                SELECT f.id, f.filename, f.file_type
                FROM files f
                LEFT JOIN summaries s ON f.id = s.file_id
                WHERE s.id IS NULL AND {' AND '.join(conditions)}
                ORDER BY f.size_bytes DESC
                LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            files_to_process = cursor.fetchall()
            
            conn.close()
            
            if not files_to_process:
                return {'processed': 0, 'successful': 0, 'failed': 0, 'details': []}
            
            results = {'processed': 0, 'successful': 0, 'failed': 0, 'details': []}
            
            for file_data in files_to_process:
                file_id, filename, file_type = file_data
                
                logger.info(f"Generating summary for: {filename}")
                
                try:
                    summary = self.generate_summary(file_id)
                    results['processed'] += 1
                    
                    if summary:
                        results['successful'] += 1
                        results['details'].append({
                            'filename': filename,
                            'file_type': file_type,
                            'success': True,
                            'summary_length': len(summary['summary']),
                            'confidence': summary['confidence']
                        })
                    else:
                        results['failed'] += 1
                        results['details'].append({
                            'filename': filename,
                            'file_type': file_type,
                            'success': False,
                            'error': 'Failed to generate summary'
                        })
                        
                except Exception as e:
                    results['failed'] += 1
                    results['details'].append({
                        'filename': filename,
                        'file_type': file_type,
                        'success': False,
                        'error': str(e)
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Error in batch summary generation: {e}")
            return {'processed': 0, 'successful': 0, 'failed': 0, 'error': str(e)}
    
    # Intelligent Q&A
    def ask_question(self, question: str, context_files: Optional[List[int]] = None, 
                    max_context_files: int = 5) -> Dict[str, Any]:
        """Ask a question about documents with AI assistance."""
        try:
            # If no specific files provided, find relevant ones
            if not context_files:
                context_files = self._find_relevant_files(question, max_context_files)
            
            # Get content from context files
            context_content = self._get_files_content(context_files[:max_context_files])
            
            if not context_content:
                return {
                    'success': False,
                    'error': 'No relevant files found or files have no content',
                    'answer': '',
                    'context_files': []
                }
            
            # Generate answer using AI
            answer = self._generate_answer(question, context_content)
            
            if answer:
                # Save Q&A to history
                self._save_qa_history(question, answer, context_files)
                
                return {
                    'success': True,
                    'answer': answer,
                    'context_files': context_files,
                    'files_used': len(context_files)
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to generate answer',
                    'answer': '',
                    'context_files': context_files
                }
                
        except Exception as e:
            logger.error(f"Error in ask_question: {e}")
            return {
                'success': False,
                'error': str(e),
                'answer': '',
                'context_files': []
            }
    
    def _find_relevant_files(self, question: str, limit: int) -> List[int]:
        """Find files relevant to the question."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Simple keyword-based search in content and summaries
            question_words = re.findall(r'\\b\\w{3,}\\b', question.lower())
            
            if not question_words:
                # Fallback to recent files with content
                cursor.execute("""
                    SELECT id FROM files
                    WHERE content_text IS NOT NULL AND content_text != ''
                    ORDER BY modified_at DESC
                    LIMIT ?
                """, (limit,))
            else:
                # Search in content and summaries
                search_pattern = '%' + '%'.join(question_words) + '%'
                cursor.execute("""
                    SELECT DISTINCT f.id,
                           CASE 
                               WHEN f.content_text LIKE ? THEN 2
                               WHEN s.summary_text LIKE ? THEN 1
                               ELSE 0
                           END as relevance_score
                    FROM files f
                    LEFT JOIN summaries s ON f.id = s.file_id
                    WHERE f.content_text LIKE ? OR s.summary_text LIKE ?
                    ORDER BY relevance_score DESC, f.modified_at DESC
                    LIMIT ?
                """, (search_pattern, search_pattern, search_pattern, search_pattern, limit))
            
            results = cursor.fetchall()
            conn.close()
            
            return [row[0] for row in results]
            
        except Exception as e:
            logger.error(f"Error finding relevant files: {e}")
            return []
    
    def _get_files_content(self, file_ids: List[int]) -> List[Dict[str, Any]]:
        """Get content and metadata for specified files."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if not file_ids:
                return []
            
            placeholders = ','.join('?' * len(file_ids))
            cursor.execute(f"""
                SELECT f.id, f.filename, f.file_type, f.content_text,
                       s.summary_text
                FROM files f
                LEFT JOIN summaries s ON f.id = s.file_id
                WHERE f.id IN ({placeholders})
                AND f.content_text IS NOT NULL AND f.content_text != ''
            """, file_ids)
            
            results = []
            for row in cursor.fetchall():
                # Limit content length for AI processing
                content = row['content_text'][:3000] if row['content_text'] else ''
                
                results.append({
                    'id': row['id'],
                    'filename': row['filename'],
                    'file_type': row['file_type'],
                    'content': content,
                    'summary': row['summary_text'] or ''
                })
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error getting files content: {e}")
            return []
    
    def _generate_answer(self, question: str, context_files: List[Dict[str, Any]]) -> Optional[str]:
        """Generate answer using AI based on context files."""
        # Build context from files
        context_parts = []
        for file_info in context_files:
            context_part = f"File: {file_info['filename']} ({file_info['file_type']})\\n"
            
            if file_info['summary']:
                context_part += f"Summary: {file_info['summary']}\\n"
            
            if file_info['content']:
                context_part += f"Content: {file_info['content'][:1500]}\\n"
            
            context_parts.append(context_part)
        
        full_context = "\\n\\n---\\n\\n".join(context_parts)
        
        system_prompt = """You are an intelligent document assistant. Answer questions based on the provided document context.
        
        Guidelines:
        - Base your answer on the provided documents
        - Be specific and cite relevant information
        - If information is not available in the documents, say so
        - Provide helpful and accurate responses
        - Keep answers concise but comprehensive"""
        
        prompt = f"""Context Documents:
{full_context}

Question: {question}

Answer:"""
        
        return self._make_ollama_request(prompt, system_prompt, max_tokens=800)
    
    def _save_qa_history(self, question: str, answer: str, context_files: List[int]):
        """Save Q&A to history."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO qa_history (question, answer, context_files, model_used)
                VALUES (?, ?, ?, ?)
            """, (question, answer, json.dumps(context_files), self.model))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving Q&A history: {e}")
    
    def get_qa_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent Q&A history."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT question, answer, context_files, created_at, rating, feedback
                FROM qa_history
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'question': row['question'],
                    'answer': row['answer'],
                    'context_files': json.loads(row['context_files']) if row['context_files'] else [],
                    'created_at': row['created_at'],
                    'rating': row['rating'],
                    'feedback': row['feedback']
                })
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error getting Q&A history: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get AI system statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = {}
            
            # Summary stats
            cursor.execute("SELECT COUNT(*) FROM summaries")
            stats['total_summaries'] = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM files f
                LEFT JOIN summaries s ON f.id = s.file_id
                WHERE f.content_text IS NOT NULL AND f.content_text != ''
                AND s.id IS NULL
            """)
            stats['files_without_summaries'] = cursor.fetchone()[0]
            
            # Q&A stats
            cursor.execute("SELECT COUNT(*) FROM qa_history")
            stats['total_questions'] = cursor.fetchone()[0]
            
            # Average confidence
            cursor.execute("SELECT AVG(confidence_score) FROM summaries WHERE confidence_score > 0")
            result = cursor.fetchone()[0]
            stats['avg_summary_confidence'] = result or 0.0
            
            # Top topics
            cursor.execute("""
                SELECT topics FROM summaries 
                WHERE topics IS NOT NULL AND topics != ''
            """)
            
            all_topics = []
            for row in cursor.fetchall():
                try:
                    topics = json.loads(row[0])
                    all_topics.extend(topics)
                except:
                    continue
            
            # Count topic frequency
            topic_counts = {}
            for topic in all_topics:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            
            # Top 10 topics
            top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            stats['top_topics'] = dict(top_topics)
            
            conn.close()
            
            # System status
            stats['ollama_available'] = self.is_ollama_available()
            stats['model_used'] = self.model
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting AI stats: {e}")
            return {}
    
    def delete_summary(self, file_id: int) -> bool:
        """Delete summary for a file."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM summaries WHERE file_id = ?", (file_id,))
            success = cursor.rowcount > 0
            
            conn.commit()
            conn.close()
            
            return success
            
        except Exception as e:
            logger.error(f"Error deleting summary: {e}")
            return False