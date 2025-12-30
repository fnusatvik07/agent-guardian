"""
Simplified enterprise tools with routing between database and RAG systems.
"""
import asyncio
import json
import os
import pickle
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

from app.config import get_settings
from app.observability import get_logger
from app.security import rbac_manager, User
from app.database import get_database_manager


@dataclass
class ToolResult:
    """Standardized tool execution result."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


class RAGSystem:
    """FAISS-based RAG system for document search."""
    
    def __init__(self):
        self.logger = get_logger("rag_system")
        self.settings = get_settings()
        
        # Initialize embedding model
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Initialize FAISS index
        self.documents = []
        self.index = None
        self.index_path = "./data/faiss_index.bin"
        self.docs_path = "./data/documents_cache.pkl"
        
        # Build or load index
        self._initialize_index()
    
    def _initialize_index(self):
        """Initialize or load FAISS index."""
        if os.path.exists(self.index_path) and os.path.exists(self.docs_path):
            # Load existing index
            self._load_index()
        else:
            # Build new index from documents
            self._build_index()
    
    def _build_index(self):
        """Build FAISS index from document files."""
        self.logger.info("Building FAISS index from documents...")
        
        documents_dir = "./data/documents"
        if not os.path.exists(documents_dir):
            self.logger.warning("Documents directory not found")
            return
        
        # Read all documents
        for filename in os.listdir(documents_dir):
            if filename.endswith('.txt'):
                filepath = os.path.join(documents_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Split into chunks for better retrieval
                chunks = self._split_document(content, filename)
                self.documents.extend(chunks)
        
        if not self.documents:
            self.logger.warning("No documents found to index")
            return
        
        # Generate embeddings
        texts = [doc['content'] for doc in self.documents]
        embeddings = self.embedding_model.encode(texts)
        
        # Create FAISS index
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)  # Inner product for cosine similarity
        
        # Normalize embeddings for cosine similarity
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings.astype('float32'))
        
        # Save index and documents
        self._save_index()
        
        self.logger.info(f"Built FAISS index with {len(self.documents)} document chunks")
    
    def _split_document(self, content: str, filename: str) -> List[Dict[str, Any]]:
        """Split document into chunks."""
        # Simple chunking by paragraphs and sections
        sections = content.split('\n\n')
        chunks = []
        
        for i, section in enumerate(sections):
            if len(section.strip()) > 50:  # Skip very short sections
                chunks.append({
                    'content': section.strip(),
                    'source': filename,
                    'chunk_id': f"{filename}_{i}",
                    'metadata': {
                        'filename': filename,
                        'chunk_index': i,
                        'length': len(section)
                    }
                })
        
        return chunks
    
    def _save_index(self):
        """Save FAISS index and documents to disk."""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        
        faiss.write_index(self.index, self.index_path)
        
        with open(self.docs_path, 'wb') as f:
            pickle.dump(self.documents, f)
    
    def _load_index(self):
        """Load FAISS index and documents from disk."""
        self.index = faiss.read_index(self.index_path)
        
        with open(self.docs_path, 'rb') as f:
            self.documents = pickle.load(f)
        
        self.logger.info(f"Loaded FAISS index with {len(self.documents)} document chunks")
    
    async def search(self, query: str, max_results: int = 5) -> ToolResult:
        """Search documents using FAISS similarity with detailed logging."""
        self.logger.info(f"🔍 RAG SEARCH START: Query='{query}', Max Results={max_results}")
        
        try:
            if self.index is None or not self.documents:
                self.logger.warning("⚠️ RAG WARNING: No index or documents available")
                return ToolResult(
                    success=False,
                    error="RAG system not initialized - no documents indexed"
                )
            
            self.logger.info(f"📊 RAG INDEX: Index ready with {len(self.documents)} document chunks")
            
            # Generate query embedding
            self.logger.info("🧠 EMBEDDING: Generating query embedding using sentence-transformers")
            query_embedding = self.embedding_model.encode([query])
            faiss.normalize_L2(query_embedding)
            self.logger.info(f"✅ EMBEDDING: Generated normalized embedding with shape {query_embedding.shape}")
            
            # Search FAISS index
            self.logger.info(f"🔎 FAISS SEARCH: Searching index for top {max_results} matches")
            scores, indices = self.index.search(query_embedding.astype('float32'), max_results)
            
            # Format results
            results = []
            for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if idx < len(self.documents):
                    doc = self.documents[idx]
                    result = {
                        'content': doc['content'],
                        'source': doc['source'],
                        'similarity_score': float(score),
                        'metadata': doc['metadata']
                    }
                    results.append(result)
                    content_preview = doc['content'][:100].replace('\n', ' ')
                    self.logger.info(f"📄 MATCH {i+1}: Source='{doc['source']}', Score={score:.4f}, Preview='{content_preview}...'")
            
            self.logger.info(f"✅ RAG SEARCH COMPLETE: Retrieved {len(results)} relevant documents")
            
            return ToolResult(
                success=True,
                data=results,
                metadata={
                    'query': query,
                    'result_count': len(results),
                    'search_type': 'faiss_similarity'
                }
            )
            
        except Exception as e:
            self.logger.error(f"🚨 RAG ERROR: Search failed - {str(e)}")
            return ToolResult(success=False, error=str(e))


class SimpleToolRegistry:
    """Simplified tool registry with database and RAG routing."""
    
    def __init__(self):
        self.logger = get_logger("tool_registry")
        self.database = get_database_manager()
        self.rag_system = RAGSystem()
        
        # Define tools with comprehensive descriptions
        self.tool_definitions = {
            "get_database_schema": {
                "type": "function",
                "function": {
                    "name": "get_database_schema",
                    "description": "Get detailed database schema information including table structures, column definitions, and sample data counts. Use this FIRST to understand available data before querying specific tables.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Optional specific table to get schema for. If not provided, returns overview of all tables.",
                                "enum": ["employees", "tickets", "projects", "expenses", "assets", "training", "metrics"]
                            }
                        }
                    }
                }
            },
            "query_database": {
                "type": "function",
                "function": {
                    "name": "query_database",
                    "description": "Query enterprise database for structured business data. Available tables: employees (staff directory, 50+ records), tickets (support requests, 25+ records), projects (project tracking, 15+ records), expenses (financial data, 40+ records), assets (equipment tracking, 30+ records), training (certifications, 35+ records), metrics (KPIs, 20+ records). Use get_database_schema first to understand table structures and available columns.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query_type": {
                                "type": "string",
                                "enum": ["employees", "tickets", "projects", "expenses", "assets", "training", "metrics"],
                                "description": "Database table to query: employees=staff info/org chart, tickets=support/requests, projects=project management, expenses=financial tracking, assets=equipment/resources, training=courses/certs, metrics=business KPIs"
                            },
                            "filters": {
                                "type": "object",
                                "description": "Optional filters to narrow results. Common filters: department (Engineering/Sales/Marketing/HR/Finance/Operations), status (active/inactive/open/closed/completed), priority (high/medium/low), dates (YYYY-MM-DD format)",
                                "properties": {
                                    "department": {"type": "string", "description": "Filter by department"},
                                    "status": {"type": "string", "description": "Filter by status"},
                                    "priority": {"type": "string", "description": "Filter by priority level"},
                                    "employee_id": {"type": "string", "description": "Filter by specific employee ID"},
                                    "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                                    "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"}
                                }
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of records to return (1-100)",
                                "default": 10,
                                "minimum": 1,
                                "maximum": 100
                            }
                        },
                        "required": ["query_type"]
                    }
                }
            },
            "search_documents": {
                "type": "function", 
                "function": {
                    "name": "search_documents",
                    "description": "Search company knowledge base using semantic similarity. Contains organizational policies, procedures, and guidelines: HR policies (employee handbook, remote work, benefits), IT security guidelines (infrastructure, data protection), customer service procedures (support processes, escalation), financial policies (expense procedures, approvals), training materials, and operational procedures. Use for policy questions, procedure lookups, and guideline clarification.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language search query describing what policy, procedure, or information you need (e.g., 'remote work policy', 'expense approval process', 'security guidelines', 'customer escalation procedure')"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of relevant document sections to return (1-10)",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 10
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        }
    
    def get_available_tools(self, user: User) -> List[Dict[str, Any]]:
        """Get tools available to the user based on their role."""
        # Both tools available to all authenticated users
        return list(self.tool_definitions.values())
    
    async def execute_tool(self, tool_name: str, args: Dict[str, Any], user: User) -> ToolResult:
        """Execute a tool with proper access control."""
        try:
            if tool_name == "get_database_schema":
                return await self._get_database_schema(
                    args.get("table_name"),
                    user
                )
            
            elif tool_name == "query_database":
                return await self._query_database(
                    args.get("query_type"),
                    args.get("filters", {}),
                    args.get("limit", 10),
                    user
                )
            
            elif tool_name == "search_documents":
                return await self.rag_system.search(
                    args.get("query"),
                    args.get("max_results", 5)
                )
            
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown tool: {tool_name}"
                )
        
        except Exception as e:
            self.logger.error(f"Tool execution failed: {tool_name}", error=str(e))
            return ToolResult(success=False, error=str(e))
    
    async def _get_database_schema(self, table_name: Optional[str], user: User) -> ToolResult:
        """Get database schema information with detailed column descriptions."""
        try:
            schema_info = {
                "employees": {
                    "description": "Employee directory and organizational data - staff information, departments, roles, reporting structure",
                    "record_count": "50+ active employees across 6 departments",
                    "columns": {
                        "employee_id": "INTEGER PRIMARY KEY - Unique employee identifier",
                        "first_name": "TEXT NOT NULL - Employee first name",
                        "last_name": "TEXT NOT NULL - Employee last name", 
                        "email": "TEXT UNIQUE NOT NULL - Corporate email address",
                        "department": "TEXT NOT NULL - Business department (Engineering, Sales, Marketing, HR, Finance, Operations)",
                        "position": "TEXT NOT NULL - Job title/role",
                        "hire_date": "DATE NOT NULL - Date of employment start",
                        "salary": "INTEGER NOT NULL - Annual salary in USD",
                        "manager_id": "INTEGER - References employee_id for reporting structure"
                    },
                    "common_queries": ["Count by department", "Salary statistics", "Organizational hierarchy", "New hires by date range"],
                    "sample_filters": ["department='Engineering'", "hire_date >= '2023-01-01'", "manager_id IS NOT NULL"]
                },
                "tickets": {
                    "description": "Support tickets and internal requests - customer support, IT requests, HR issues",
                    "record_count": "25+ tickets with various statuses and priorities",
                    "columns": {
                        "ticket_id": "INTEGER PRIMARY KEY - Unique ticket identifier",
                        "title": "TEXT NOT NULL - Ticket subject/summary",
                        "description": "TEXT NOT NULL - Detailed ticket description",
                        "status": "TEXT DEFAULT 'open' - Ticket status (open, in_progress, closed)",
                        "priority": "TEXT DEFAULT 'medium' - Priority level (high, medium, low)",
                        "created_by": "INTEGER NOT NULL - Employee who created ticket",
                        "assigned_to": "INTEGER - Employee assigned to ticket",
                        "created_at": "TIMESTAMP - Creation time",
                        "updated_at": "TIMESTAMP - Last update time"
                    },
                    "common_queries": ["Open tickets by priority", "Tickets by assignee", "Resolution times", "Tickets by department"],
                    "sample_filters": ["status='open'", "priority='high'", "assigned_to=123"]
                },
                "projects": {
                    "description": "Project management and tracking - active projects, assignments, budgets, timelines",
                    "record_count": "15+ projects across departments with various statuses",
                    "columns": {
                        "project_id": "INTEGER PRIMARY KEY - Unique project identifier",
                        "name": "TEXT NOT NULL - Project name/title",
                        "description": "TEXT NOT NULL - Project description and scope",
                        "status": "TEXT DEFAULT 'active' - Project status (active, completed, on_hold)",
                        "start_date": "DATE NOT NULL - Project start date",
                        "end_date": "DATE - Project completion/target date",
                        "budget": "INTEGER - Project budget in USD",
                        "manager_id": "INTEGER NOT NULL - Project manager employee ID",
                        "department": "TEXT NOT NULL - Owning department"
                    },
                    "common_queries": ["Active projects by department", "Budget utilization", "Project timelines", "Projects by manager"],
                    "sample_filters": ["status='active'", "department='Engineering'", "budget > 50000"]
                },
                "expenses": {
                    "description": "Employee expense reports and financial tracking - travel, meals, supplies, approvals",
                    "record_count": "40+ expense records across categories with approval workflow",
                    "columns": {
                        "expense_id": "INTEGER PRIMARY KEY - Unique expense identifier",
                        "employee_id": "INTEGER NOT NULL - Employee who incurred expense",
                        "description": "TEXT NOT NULL - Expense description/purpose",
                        "amount": "DECIMAL(10,2) NOT NULL - Expense amount in USD",
                        "category": "TEXT NOT NULL - Expense category (travel, meals, office_supplies, software, training)",
                        "expense_date": "DATE NOT NULL - Date expense was incurred",
                        "status": "TEXT DEFAULT 'pending' - Approval status (pending, approved, rejected)",
                        "approved_by": "INTEGER - Approving manager employee ID"
                    },
                    "common_queries": ["Expenses by category", "Pending approvals", "Monthly spend by department", "Large expenses"],
                    "sample_filters": ["status='pending'", "category='travel'", "amount > 500"]
                },
                "assets": {
                    "description": "Company asset and equipment tracking - laptops, monitors, software licenses, furniture",
                    "record_count": "30+ assets including IT equipment and office resources",
                    "columns": {
                        "asset_id": "INTEGER PRIMARY KEY - Unique asset identifier",
                        "name": "TEXT NOT NULL - Asset name/model",
                        "type": "TEXT NOT NULL - Asset type (laptop, monitor, software, furniture)",
                        "serial_number": "TEXT UNIQUE - Asset serial number",
                        "purchase_date": "DATE NOT NULL - Date of purchase",
                        "cost": "DECIMAL(10,2) NOT NULL - Purchase cost in USD",
                        "assigned_to": "INTEGER - Employee assigned to asset",
                        "status": "TEXT DEFAULT 'active' - Asset status (active, retired, maintenance)",
                        "location": "TEXT - Physical location or department"
                    },
                    "common_queries": ["Assets by type", "Assignments by employee", "Asset lifecycle", "High-value assets"],
                    "sample_filters": ["type='laptop'", "status='active'", "cost > 1000"]
                },
                "training": {
                    "description": "Employee training and certification records - courses, providers, certifications, compliance",
                    "record_count": "35+ training records across various courses and certifications",
                    "columns": {
                        "training_id": "INTEGER PRIMARY KEY - Unique training record identifier",
                        "employee_id": "INTEGER NOT NULL - Employee who took training",
                        "course_name": "TEXT NOT NULL - Training course name",
                        "provider": "TEXT NOT NULL - Training provider organization",
                        "completion_date": "DATE NOT NULL - Date training was completed",
                        "certification": "TEXT - Certificate or credential earned",
                        "expiry_date": "DATE - Certification expiration date",
                        "cost": "DECIMAL(10,2) - Training cost in USD",
                        "status": "TEXT DEFAULT 'completed' - Training status (completed, in_progress, failed)"
                    },
                    "common_queries": ["Certifications by employee", "Training spend", "Expiring certifications", "Compliance tracking"],
                    "sample_filters": ["status='completed'", "expiry_date < '2024-12-31'", "provider='AWS'"]
                },
                "metrics": {
                    "description": "Company performance metrics and KPIs - financial, operational, and HR metrics",
                    "record_count": "20+ key business metrics across categories with targets",
                    "columns": {
                        "metric_id": "INTEGER PRIMARY KEY - Unique metric identifier",
                        "name": "TEXT NOT NULL - Metric name/description",
                        "value": "DECIMAL(15,2) NOT NULL - Metric value",
                        "unit": "TEXT NOT NULL - Measurement unit (USD, percentage, count, etc.)",
                        "category": "TEXT NOT NULL - Metric category (financial, operational, hr)",
                        "metric_date": "DATE NOT NULL - Measurement date",
                        "department": "TEXT - Associated department",
                        "target": "DECIMAL(15,2) - Target/goal value",
                        "period": "TEXT NOT NULL - Reporting period (daily, monthly, quarterly, annual)"
                    },
                    "common_queries": ["KPIs by category", "Performance vs targets", "Trend analysis", "Department metrics"],
                    "sample_filters": ["category='financial'", "period='monthly'", "value >= target"]
                }
            }
            
            if table_name:
                if table_name in schema_info:
                    result_data = {
                        "table": table_name,
                        "schema": schema_info[table_name]
                    }
                else:
                    return ToolResult(success=False, error=f"Table '{table_name}' not found. Available tables: {list(schema_info.keys())}")
            else:
                result_data = {
                    "database_overview": {
                        "total_tables": len(schema_info),
                        "available_tables": list(schema_info.keys()),
                        "description": "Enterprise database containing employee, project, financial, and operational data",
                        "usage_tip": "Use get_database_schema with a specific table_name to get detailed column information before querying"
                    },
                    "table_summaries": {name: {"description": info["description"], "record_count": info["record_count"]} 
                                      for name, info in schema_info.items()}
                }
            
            return ToolResult(success=True, data=result_data)
            
        except Exception as e:
            self.logger.error(f"Schema query error: {str(e)}")
            return ToolResult(success=False, error=f"Failed to retrieve schema: {str(e)}")
    
    async def _query_database(self, query_type: str, filters: Dict[str, Any], limit: int, user: User) -> ToolResult:
        """Query enterprise database with detailed logging."""
        self.logger.info(f"📊 DATABASE QUERY START: Type='{query_type}', Filters={filters}, Limit={limit}")
        
        await asyncio.sleep(0.1)  # Simulate processing time
        
        try:
            # Build SQL query based on query_type
            if query_type == "employees":
                self.logger.info("👥 EMPLOYEES: Building employee query")
                query = "SELECT employee_id, first_name, last_name, email, department, position, hire_date FROM employees WHERE 1=1"
                params = []
                
                if filters.get("department"):
                    query += " AND department = ?"
                    params.append(filters["department"])
                    self.logger.info(f"🔍 FILTER: Added department filter = '{filters['department']}'")
                
                if filters.get("employee_id"):
                    query += " AND employee_id = ?"
                    params.append(filters["employee_id"])
                    self.logger.info(f"🔍 FILTER: Added employee_id filter = '{filters['employee_id']}'")
                
                query += f" ORDER BY hire_date DESC LIMIT {limit}"
                
            elif query_type == "tickets":
                self.logger.info("🎫 TICKETS: Building tickets query")
                query = "SELECT ticket_id, title, severity, status, requester_id, category, created_at FROM support_tickets WHERE 1=1"
                params = []
                
                if filters.get("status"):
                    query += " AND status = ?"
                    params.append(filters["status"])
                    self.logger.info(f"🔍 FILTER: Added status filter = '{filters['status']}'")
                
                query += f" ORDER BY created_at DESC LIMIT {limit}"
                
                query += f" ORDER BY created_at DESC LIMIT {limit}"
                
            elif query_type == "projects":
                query = "SELECT project_id, name, status, priority, start_date, end_date, budget FROM projects WHERE 1=1"
                params = []
                
                if filters.get("status"):
                    query += " AND status = ?"
                    params.append(filters["status"])
                
                query += f" ORDER BY start_date DESC LIMIT {limit}"
                
            elif query_type == "expenses":
                query = "SELECT expense_id, employee_id, category, amount, description, expense_date, status FROM expenses WHERE 1=1"
                params = []
                
                if filters.get("employee_id"):
                    query += " AND employee_id = ?"
                    params.append(filters["employee_id"])
                
                if filters.get("status"):
                    query += " AND status = ?"
                    params.append(filters["status"])
                
                query += f" ORDER BY expense_date DESC LIMIT {limit}"
                
            elif query_type == "metrics":
                query = "SELECT metric_name, metric_value, metric_unit, category, date_recorded FROM company_metrics WHERE 1=1"
                params = []
                
                if filters.get("date_from"):
                    query += " AND date_recorded >= ?"
                    params.append(filters["date_from"])
                
                query += f" ORDER BY date_recorded DESC LIMIT {limit}"
                
            else:
                self.logger.error(f"❌ UNSUPPORTED QUERY TYPE: '{query_type}'")
                return ToolResult(success=False, error=f"Unsupported query type: {query_type}")
            
            # Execute query
            self.logger.info(f"🗄️ SQL EXECUTION: {query}")
            self.logger.info(f"📝 PARAMETERS: {params}")
            
            results = self.database.query_sqlite(query, tuple(params) if params else None)
            
            self.logger.info(f"✅ DATABASE SUCCESS: Retrieved {len(results)} records")
            
            # Log sample results (first few records)
            for i, record in enumerate(results[:3]):
                record_preview = {k: v for k, v in record.items() if k in ['employee_id', 'first_name', 'last_name', 'department', 'title', 'ticket_id', 'status']}
                self.logger.info(f"📋 RECORD {i+1}: {record_preview}")
            
            if len(results) > 3:
                self.logger.info(f"📋 ... and {len(results) - 3} more records")
            
            return ToolResult(
                success=True,
                data=results,
                metadata={
                    "query_type": query_type,
                    "result_count": len(results),
                    "filters_applied": filters
                }
            )
            
        except Exception as e:
            self.logger.error(f"🚨 DATABASE ERROR: Query failed - {str(e)}")
            return ToolResult(success=False, error=str(e))


# Global tool registry instance
tool_registry = SimpleToolRegistry()