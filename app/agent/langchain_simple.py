"""
Simple LangChain agent following official v1.0 documentation - NO RBAC.
"""
import json
import asyncio
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.tools import tool

from app.config import get_settings
from app.observability import get_logger


@dataclass
class AgentResponse:
    """Standardized agent response format."""
    content: Optional[str]
    tool_calls: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    finish_reason: str = "stop"


class SimpleLangChainAgent:
    """Simple agent following LangChain v1.0 official docs - no RBAC."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger("simple_agent")
        self.agent = None
        self._initialized = False
        self.current_user = None  # Keep for compatibility but not used
    
    def set_user_context(self, user):
        """Set user context for compatibility - no restrictions applied."""
        self.current_user = user
        self.logger.info(f"User context set: {user.user_id} (no restrictions)")
    
    def _initialize(self):
        """Initialize once using create_agent."""
        if self._initialized:
            return
            
        # Create model
        import os
        api_key = self.settings.llm.openai_api_key or os.getenv('OPENAI_API_KEY')
        
        if not api_key:
            raise ValueError("OpenAI API key not found. Please set OPENAI_API_KEY environment variable.")
        
        self.logger.info(f"🔑 API KEY: Using key starting with {api_key[:10]}...")
        
        model = ChatOpenAI(
            model=self.settings.llm.model_name,
            api_key=api_key,
            temperature=0.1
        )
        
        # Create all tools
        tools = self._create_tools()
        
        # Create agent using official create_agent function
        self.agent = create_agent(
            model=model,
            tools=tools,
            system_prompt="""You are a helpful enterprise assistant. 

CRITICAL: You MUST ALWAYS use the available tools to answer questions. Never use your training data or make assumptions.

Available tools:
- execute_sql_query: Convert natural language to SQL and query the employee database
- get_employee_count: Get total number of employees 
- search_policies: Search company policies and documents

For employee-related questions (names, emails, departments, salaries): Use execute_sql_query tool
For simple employee counts: Use get_employee_count tool  
For policy, document, or guideline questions: Use search_policies tool

ALWAYS call the appropriate tool first before providing any answer. Do not provide information without calling a tool."""
        )
        
        self._initialized = True
        self.logger.info("Agent initialized with all tools available")
    
    def _create_tools(self):
        """Create all tools - no restrictions."""
        tools = []
        
        self.logger.info("Creating all tools with no access restrictions")
        
        # Execute SQL Query Tool
        @tool
        def execute_sql_query(natural_language_query: str) -> str:
            """Convert natural language to SQL and execute it against the employee database.
            
            EMPLOYEE DATABASE SCHEMA:
            Table: employees
            Columns:
            - id INTEGER PRIMARY KEY AUTOINCREMENT
            - employee_id TEXT UNIQUE NOT NULL  
            - first_name TEXT NOT NULL
            - last_name TEXT NOT NULL
            - email TEXT UNIQUE NOT NULL
            - department TEXT NOT NULL (values: Engineering, Marketing, Finance, HR, IT)
            - position TEXT NOT NULL
            - manager_id TEXT (references employee_id of another employee who is the manager)
            - hire_date DATE NOT NULL
            - salary REAL
            - status TEXT DEFAULT 'active'
            - created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            
            EXAMPLES:
            - "What is Sarah Johnson's email?" -> SELECT first_name, last_name, email FROM employees WHERE first_name = 'Sarah' AND last_name = 'Johnson'
            - "List all employees in Engineering" -> SELECT first_name, last_name, position FROM employees WHERE department = 'Engineering'
            - "Average salary by department" -> SELECT department, AVG(salary) as avg_salary FROM employees GROUP BY department
            - "Who are the managers?" -> SELECT DISTINCT m.first_name, m.last_name, m.position FROM employees e JOIN employees m ON e.manager_id = m.employee_id
            - "Show employees and their managers" -> SELECT e.first_name || ' ' || e.last_name as employee, m.first_name || ' ' || m.last_name as manager FROM employees e LEFT JOIN employees m ON e.manager_id = m.employee_id
            
            Returns:
                The query results formatted as text
            """
            from app.observability import agent_logger
            
            agent_logger.log_tool_call_start("execute_sql_query", {"query": natural_language_query})
            self.logger.info(f"🔧 SQL TOOL: Converting query: {natural_language_query}")
            
            try:
                import sqlite3
                import os
                from openai import OpenAI
                
                schema_context = """
                DATABASE SCHEMA:
                Table: employees
                Columns:
                - id INTEGER PRIMARY KEY AUTOINCREMENT
                - employee_id TEXT UNIQUE NOT NULL  
                - first_name TEXT NOT NULL
                - last_name TEXT NOT NULL
                - email TEXT UNIQUE NOT NULL
                - department TEXT NOT NULL (values: Engineering, Marketing, Finance, HR, IT)
                - position TEXT NOT NULL
                - manager_id TEXT (references employee_id of another employee who is the manager)
                - hire_date DATE NOT NULL
                - salary REAL
                - status TEXT DEFAULT 'active'
                - created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                """
                
                sql_prompt = f"""
                {schema_context}
                
                Convert this natural language query to SQL:
                "{natural_language_query}"
                
                Rules:
                1. Return ONLY the SQL query, no explanation
                2. Use proper JOIN syntax for manager relationships
                3. Use appropriate aggregation functions (COUNT, AVG, SUM, etc.)
                4. Use LIKE with % for partial name matches
                5. Use || for string concatenation in SQLite
                6. Always include relevant columns in SELECT
                7. Use LEFT JOIN for optional relationships like managers
                
                SQL:
                """
                
                client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
                response = client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[{"role": "user", "content": sql_prompt}],
                    temperature=0,
                    max_tokens=200
                )
                
                sql = response.choices[0].message.content.strip()
                sql = sql.replace('```sql', '').replace('```', '').strip()
                
                self.logger.info(f"🔧 SQL GENERATED: {sql}")
                
                # Execute SQL
                conn = sqlite3.connect('data/governance_agent.db')
                cursor = conn.cursor()
                cursor.execute(sql)
                results = cursor.fetchall()
                
                column_names = [description[0] for description in cursor.description]
                conn.close()
                
                if results:
                    if len(results) == 1 and len(results[0]) == 1:
                        result_text = str(results[0][0])
                    else:
                        formatted_results = []
                        
                        if len(column_names) > 1:
                            formatted_results.append(" | ".join(column_names))
                            formatted_results.append("-" * (len(" | ".join(column_names))))
                        
                        for row in results:
                            formatted_row = " | ".join(str(col) if col is not None else "NULL" for col in row)
                            formatted_results.append(formatted_row)
                        
                        result_text = "\\n".join(formatted_results)
                    
                    self.logger.info(f"✅ SQL RESULTS: Found {len(results)} row(s)")
                    agent_logger.log_tool_call_result("execute_sql_query", result_text, success=True)
                    return result_text
                else:
                    error_msg = "No results found for your query"
                    self.logger.info(f"❌ NO RESULTS: {error_msg}")
                    agent_logger.log_tool_call_result("execute_sql_query", error_msg, success=False)
                    return error_msg
            
            except Exception as e:
                error_msg = f"Error executing SQL query: {str(e)}"
                self.logger.error(f"❌ SQL ERROR: {error_msg}")
                agent_logger.log_tool_call_result("execute_sql_query", error_msg, success=False, error=str(e))
                return error_msg

        # Employee Count Tool
        @tool 
        def get_employee_count() -> str:
            """Get total number of employees in the company.
            
            Returns:
                The total employee count as a string
            """
            from app.observability import agent_logger
            
            agent_logger.log_tool_call_start("get_employee_count", {})
            self.logger.info("🔧 TOOL: Getting employee count")
            
            try:
                import sqlite3
                conn = sqlite3.connect('data/governance_agent.db')
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM employees WHERE status = 'active'")
                count = cursor.fetchone()[0]
                conn.close()
                
                result = f"Total active employees: {count}"
                self.logger.info(f"✅ EMPLOYEE COUNT: {result}")
                agent_logger.log_tool_call_result("get_employee_count", result, success=True)
                return result
                
            except Exception as e:
                error_msg = f"Error getting employee count: {str(e)}"
                self.logger.error(f"❌ COUNT ERROR: {error_msg}")
                agent_logger.log_tool_call_result("get_employee_count", error_msg, success=False, error=str(e))
                return error_msg

        # Search Policies Tool
        @tool
        def search_policies(query: str) -> str:
            """Search company policies and documents.
            
            Args:
                query: Search query for policies
                
            Returns:
                Search results from policy documents
            """
            from app.observability import agent_logger
            
            agent_logger.log_tool_call_start("search_policies", {"query": query})
            self.logger.info(f"🔧 TOOL: Searching policies for: {query}")
            
            try:
                import os
                import glob
                
                # Simple file search in documents
                doc_dir = "data/documents"
                if not os.path.exists(doc_dir):
                    return "No policy documents found"
                
                results = []
                for file_path in glob.glob(os.path.join(doc_dir, "*.txt")):
                    try:
                        with open(file_path, 'r') as f:
                            content = f.read().lower()
                            if query.lower() in content:
                                filename = os.path.basename(file_path)
                                results.append(f"Found in: {filename}")
                    except Exception as e:
                        continue
                
                if results:
                    result = "Policy search results:\\n" + "\\n".join(results[:5])
                else:
                    result = f"No policies found matching '{query}'"
                
                self.logger.info(f"✅ POLICY SEARCH: Found {len(results)} matches")
                agent_logger.log_tool_call_result("search_policies", result, success=True)
                return result
                
            except Exception as e:
                error_msg = f"Error searching policies: {str(e)}"
                self.logger.error(f"❌ SEARCH ERROR: {error_msg}")
                agent_logger.log_tool_call_result("search_policies", error_msg, success=False, error=str(e))
                return error_msg
        
        tools = [execute_sql_query, get_employee_count, search_policies]
        
        self.logger.info(f"✅ Created {len(tools)} tools: {[tool.name for tool in tools]}")
        return tools
    
    async def chat_completion(self, messages: List[Dict[str, str]]) -> AgentResponse:
        """Process messages and return response."""
        self._initialize()
        
        try:
            # Extract user message
            user_message = messages[-1]["content"] if messages else ""
            
            self.logger.info(f"🤖 PROCESSING: {user_message}")
            
            # Use the agent - LangChain v1 create_agent format
            result = await self.agent.ainvoke({"messages": messages})
            
            # Extract content and tool calls from LangChain v1 format
            tool_calls = []
            content = ""
            
            # LangChain v1 create_agent returns messages in result
            if isinstance(result, dict) and "messages" in result:
                messages_result = result["messages"]
                for msg in messages_result:
                    # Look for AIMessage with content
                    if hasattr(msg, 'content') and msg.content:
                        content = msg.content
                    # Look for tool calls
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            tool_calls.append({
                                "tool": tool_call.get("name", "unknown"),
                                "success": True,
                                "error": None
                            })
            else:
                # Fallback - try direct content extraction
                content = str(result) if result else "No response generated"
            
            self.logger.info(f"✅ RESPONSE: Generated '{content[:100]}...' with {len(tool_calls)} tool calls")
            
            return AgentResponse(
                content=content,
                tool_calls=tool_calls,
                metadata={"model": "gpt-4-turbo-preview"},
                finish_reason="stop"
            )
            
        except Exception as e:
            self.logger.error(f"❌ AGENT ERROR: {str(e)}")
            return AgentResponse(
                content=f"I apologize, but I encountered an error: {str(e)}",
                tool_calls=[],
                metadata={"error": str(e)},
                finish_reason="error"
            )

# Create global instance
simple_agent = SimpleLangChainAgent()