"""Enhanced search specifically for legal documents."""

import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import re
from loguru import logger


class LegalDocumentSearch:
    """Specialized search for legal and financial documents."""
    
    def __init__(self, db_path: str = "data/indexes/files.db"):
        self.db_path = db_path
        
        # Legal keywords in multiple languages
        self.legal_keywords = {
            'contracts': ['contract', 'contrat', 'vertrag', 'overeenkomst', 'договор'],
            'loans': ['loan', 'prêt', 'crédit', 'lening', 'darlehen', 'кредит'],
            'agreements': ['agreement', 'accord', 'vereinbarung', 'overeenkomst', 'соглашение'],
            'property': ['property', 'propriété', 'immobilier', 'eigendom', 'immobilie', 'недвижимость'],
            'sale': ['sale', 'vente', 'verkauf', 'verkoop', 'продажа'],
            'purchase': ['purchase', 'achat', 'kauf', 'aankoop', 'покупка'],
            'notary': ['notary', 'notaire', 'notar', 'notaris', 'нотариус'],
            'deed': ['deed', 'acte', 'urkunde', 'akte', 'акт'],
            'invoice': ['invoice', 'facture', 'rechnung', 'factuur', 'счет'],
            'payment': ['payment', 'paiement', 'zahlung', 'betaling', 'платеж']
        }
        
        # Common legal document patterns
        self.amount_patterns = [
            r'\b\d{1,3}[.,]\d{3}(?:[.,]\d{2})?\s*(?:€|EUR|USD|\$)',  # 15.000,00 €
            r'€\s*\d{1,3}[.,]\d{3}',  # €15,000
            r'\b\d{4,6}\s*(?:euros?|dollars?)',  # 15000 euros
        ]
        
        # Important names/entities to track
        self.entities_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b'  # Proper names
    
    def search_legal_documents(
        self,
        query: Optional[str] = None,
        document_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        amount_min: Optional[float] = None,
        amount_max: Optional[float] = None,
        entities: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Advanced search for legal documents.
        
        Args:
            query: Free text search query
            document_type: Type of legal document (contract, loan, property, etc.)
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            amount_min: Minimum amount mentioned
            amount_max: Maximum amount mentioned
            entities: List of names/entities to search for (Dupont, etc.)
            limit: Maximum results
        """
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build dynamic query
        conditions = []
        params = []
        
        # Search in both filename and content
        if query:
            # Expand query with legal keywords
            expanded_terms = self._expand_legal_terms(query)
            term_conditions = []
            for term in expanded_terms:
                term_conditions.append("(filename LIKE ? OR path LIKE ? OR content_text LIKE ?)")
                search_term = f"%{term}%"
                params.extend([search_term, search_term, search_term])
            
            if term_conditions:
                conditions.append(f"({' OR '.join(term_conditions)})")
        
        # Filter by document type using keywords
        if document_type and document_type in self.legal_keywords:
            type_conditions = []
            for keyword in self.legal_keywords[document_type]:
                type_conditions.append("(filename LIKE ? OR content_text LIKE ?)")
                keyword_term = f"%{keyword}%"
                params.extend([keyword_term, keyword_term])
            conditions.append(f"({' OR '.join(type_conditions)})")
        
        # Date range filter
        if date_from:
            conditions.append("modified_at >= ?")
            params.append(date_from)
        
        if date_to:
            conditions.append("modified_at <= ?")
            params.append(date_to)
        
        # Entity search (names, companies)
        if entities:
            entity_conditions = []
            for entity in entities:
                entity_conditions.append("(filename LIKE ? OR content_text LIKE ?)")
                entity_term = f"%{entity}%"
                params.extend([entity_term, entity_term])
            conditions.append(f"({' OR '.join(entity_conditions)})")
        
        # Priority legal file types
        legal_extensions = "extension IN ('.pdf', '.doc', '.docx', '.rtf', '.msg', '.eml', '.txt')"
        conditions.append(legal_extensions)
        
        # Build final query
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query_sql = f"""
            SELECT *,
                   CASE 
                       WHEN extension IN ('.pdf', '.doc', '.docx') THEN 1
                       WHEN extension IN ('.msg', '.eml') THEN 2
                       ELSE 3
                   END as priority_score
            FROM files
            WHERE {where_clause}
            ORDER BY priority_score, modified_at DESC
            LIMIT ?
        """
        
        params.append(limit)
        
        logger.debug(f"Executing legal search with {len(conditions)} conditions")
        cursor.execute(query_sql, params)
        
        results = []
        for row in cursor:
            result = dict(row)
            
            # Add relevance scoring
            result['relevance_score'] = self._calculate_relevance(result, query, entities)
            
            # Extract amounts if present in content
            if result.get('content_text'):
                result['detected_amounts'] = self._extract_amounts(result['content_text'])
            
            results.append(result)
        
        conn.close()
        
        # Sort by relevance
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        logger.info(f"Found {len(results)} legal documents")
        return results
    
    def _expand_legal_terms(self, query: str) -> List[str]:
        """Expand query with multilingual legal terms."""
        terms = [query]
        query_lower = query.lower()
        
        # Check if query matches any legal category
        for category, keywords in self.legal_keywords.items():
            for keyword in keywords:
                if keyword in query_lower:
                    # Add all translations
                    terms.extend(keywords)
                    break
        
        return list(set(terms))
    
    def _calculate_relevance(self, document: Dict, query: Optional[str], entities: Optional[List[str]]) -> float:
        """Calculate relevance score for legal document."""
        score = 0.0
        
        # File type scoring
        if document.get('extension', '').lower() in ['.pdf', '.doc', '.docx']:
            score += 10
        elif document.get('extension', '').lower() in ['.msg', '.eml']:
            score += 8
        
        # Query match in filename
        if query and document.get('filename'):
            if query.lower() in document['filename'].lower():
                score += 20
        
        # Query match in content
        if query and document.get('content_text'):
            content_lower = document['content_text'].lower()
            if query.lower() in content_lower:
                score += 15
                # Count occurrences
                occurrences = content_lower.count(query.lower())
                score += min(occurrences * 2, 10)
        
        # Entity matches
        if entities:
            for entity in entities:
                if document.get('filename') and entity.lower() in document['filename'].lower():
                    score += 15
                if document.get('content_text') and entity.lower() in document['content_text'].lower():
                    score += 10
        
        # Legal keyword bonus
        if document.get('content_text'):
            content_lower = document['content_text'].lower()
            for category, keywords in self.legal_keywords.items():
                for keyword in keywords:
                    if keyword in content_lower:
                        score += 5
                        break
        
        return score
    
    def _extract_amounts(self, text: str) -> List[str]:
        """Extract monetary amounts from text."""
        amounts = []
        for pattern in self.amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            amounts.extend(matches)
        return amounts
    
    def find_related_documents(self, document_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Find documents related to a given document."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get the source document
        cursor.execute("SELECT * FROM files WHERE id = ?", (document_id,))
        source_doc = dict(cursor.fetchone())
        
        if not source_doc:
            return []
        
        # Extract key information
        filename_parts = Path(source_doc['filename']).stem.split('_')
        
        # Find related documents
        conditions = []
        params = []
        
        # Same directory
        conditions.append("parent_dir = ?")
        params.append(source_doc.get('parent_dir', ''))
        
        # Similar filenames
        for part in filename_parts:
            if len(part) > 3:  # Skip short parts
                conditions.append("filename LIKE ?")
                params.append(f"%{part}%")
        
        # Exclude the source document
        conditions.append("id != ?")
        params.append(document_id)
        
        query = f"""
            SELECT * FROM files
            WHERE {' OR '.join(conditions[:2])}
            AND id != ?
            ORDER BY modified_at DESC
            LIMIT ?
        """
        
        params = params[:2] + [document_id, limit]
        cursor.execute(query, params)
        
        results = [dict(row) for row in cursor]
        conn.close()
        
        return results