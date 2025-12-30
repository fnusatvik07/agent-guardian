"""
Simple LangChain agent following official v1.0 documentation.
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
    """Simple agent following LangChain v1.0 official docs."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger("simple_agent")
        self.agent = None
        self._initialized = False
        self.current_user = None  # Store current user context for RBAC
    
    def set_user_context(self, user):
        """Set the current user context for RBAC checks."""
        self.current_user = user
        self.logger.info(f"User context set: {user.user_id} with role {user.role.value}")
    
    def _initialize(self):
        """Initialize once using create_agent."""
        if self._initialized:
            return
            
        # Create model
        import os
        api_key = self.settings.llm.openai_api_key or os.getenv('OPENAI_API_KEY')
        
        if not api_key:
            raise ValueError("OpenAI API key not found. Please set OPENAI_API_KEY environment variable.")
        
        self.logger.info(f"✅ OpenAI API key found: {api_key[:20]}...")
            
        model = ChatOpenAI(
            model=self.settings.llm.model_name,
            api_key=api_key,
            temperature=0.1
        )
        
        # Create role-based tools
        tools = self._create_tools()
        
        # Create agent using official create_agent function
        self.agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=f"""You are a helpful enterprise assistant. 

CRITICAL: You MUST ALWAYS use the available tools to answer questions. Never use your training data or make assumptions.

Available tools based on user permissions:
{self._get_available_tools_description()}

For employee-related questions: Use appropriate database tools if available
For policy, document, or guideline questions: Use search_policies tool

ALWAYS call the appropriate tool first before providing any answer. Do not provide information without calling a tool."""
        )
        
        self._initialized = True
        self.logger.info("Agent initialized with create_agent")
    
    def _get_available_tools_description(self):
        """Get description of available tools based on user role."""
        if not self.current_user:
            return "No user context available"
            
        from app.security import rbac_manager
        
        if self.current_user.role.value == "admin":
            allowed_tools = self.settings.security.admin_allowed_tools
        else:
            allowed_tools = self.settings.security.employee_allowed_tools
            
        descriptions = []
        if "execute_sql_query" in allowed_tools:
            descriptions.append("- execute_sql_query: Full database access for complex queries")
        if "get_employee_count" in allowed_tools:
            descriptions.append("- get_employee_count: Basic employee statistics")
        if "search_policies" in allowed_tools:
            descriptions.append("- search_policies: Search company policies and documents")
            
        return "\\n".join(descriptions) if descriptions else "Limited tool access"
    
    def _create_tools(self):
        """Create tools based on user permissions with detailed logging."""
        from app.security import rbac_manager
        
        tools = []
        
        # Get allowed tools based on user role
        if self.current_user:
            if self.current_user.role.value == "admin":
                allowed_tools = self.settings.security.admin_allowed_tools
            else:
                allowed_tools = self.settings.security.employee_allowed_tools
        else:
            # Fallback to employee tools if no user context
            allowed_tools = self.settings.security.employee_allowed_tools
            
        self.logger.info(f"Creating tools for role: {self.current_user.role.value if self.current_user else 'unknown'}")
        self.logger.info(f"Allowed tools: {allowed_tools}")
        
        # Execute SQL Query Tool (Admin Only)
        if "execute_sql_query" in allowed_tools:
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
                
                Args:
                    natural_language_query: A natural language question about employees
                
                Returns:
                    The query results formatted as text
                """
                # RBAC Check
                if not self.current_user or not rbac_manager.check_tool_access(self.current_user, "execute_sql_query"):
                    return f"Access denied: User role '{self.current_user.role.value if self.current_user else 'unknown'}' cannot access full database queries. Please contact an administrator."
                
                from app.observability import agent_logger
                
                agent_logger.log_tool_call_start("execute_sql_query", {"query": natural_language_query})
                self.logger.info(f"🔧 SQL TOOL: Converting query: {natural_language_query}")
                
                try:
                    import sqlite3
                    import os
                    from openai import OpenAI
                    
                    # Use LLM to convert natural language to SQL with proper schema context
                    schema_context = """
                    DATABASE SCHEMA:
                    Table: employees
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
                    # Clean up the SQL - remove any markdown formatting
                    sql = sql.replace('```sql', '').replace('```', '').strip()
                    
                    self.logger.info(f"🔧 SQL GENERATED: {sql}")
                    
                    # Execute SQL
                    conn = sqlite3.connect('data/governance_agent.db')
                    cursor = conn.cursor()
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    
                    # Get column names for better formatting
                    column_names = [description[0] for description in cursor.description]
                    conn.close()
                    
                    if results:
                        # Format results with column headers
                        if len(results) == 1 and len(results[0]) == 1:
                            # Single value result (like COUNT)
                            result_text = str(results[0][0])
                        else:
                            # Multiple columns/rows - create a formatted table
                            formatted_results = []
                            
                            # Add header if multiple columns
                            if len(column_names) > 1:
                                formatted_results.append(" | ".join(column_names))
                                formatted_results.append("-" * (len(" | ".join(column_names))))
                            
                            # Add data rows
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
            
            tools.append(execute_sql_query)
            self.logger.info("✅ Added execute_sql_query tool (admin access)")

        # Employee Count Tool (Available to all roles)
        if "get_employee_count" in allowed_tools:
            @tool
            def get_employee_count() -> str:
                """Get the total number of employees in the company database."""
                # RBAC Check
                if not self.current_user or not rbac_manager.check_tool_access(self.current_user, "get_employee_count"):
                    return f"Access denied: User role '{self.current_user.role.value if self.current_user else 'unknown'}' cannot access employee count data."
                
                from app.observability import agent_logger
                
                agent_logger.log_tool_call_start("get_employee_count", {})
                self.logger.info("🔧 TOOL CALLED: get_employee_count - Starting employee count query")
                
                try:
                    import sqlite3
                    
                    # Simple count query
                    conn = sqlite3.connect('data/governance_agent.db')
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM employees WHERE status = 'active'")
                    count = cursor.fetchone()[0]
                    conn.close()
                    
                    result_text = f"The company has {count} active employees."
                    self.logger.info(f"✅ EMPLOYEE COUNT: {count}")
                    agent_logger.log_tool_call_result("get_employee_count", result_text, success=True)
                    return result_text
                
                except Exception as e:
                    error_msg = f"Error getting employee count: {str(e)}"
                    self.logger.error(f"❌ COUNT ERROR: {error_msg}")
                    agent_logger.log_tool_call_result("get_employee_count", error_msg, success=False, error=str(e))
                    return error_msg
            
            tools.append(get_employee_count)
            self.logger.info("✅ Added get_employee_count tool")

        # Search Policies Tool (Available to all roles)
        if "search_policies" in allowed_tools:
            @tool
            def search_policies(topic: str) -> str:
                """Search company policies and documents for information about a specific topic."""
                # RBAC Check (policies are generally accessible to all employees)
                if not self.current_user or not rbac_manager.check_tool_access(self.current_user, "search_policies"):
                    return f"Access denied: User role '{self.current_user.role.value if self.current_user else 'unknown'}' cannot access policy documents."
                
                from app.observability import agent_logger
                
                agent_logger.log_tool_call_start("search_policies", {"topic": topic})
                self.logger.info(f"🔧 TOOL CALLED: search_policies - Searching for topic: '{topic}'")
                
                try:
                    import os
                    import re
                    
                    # Search in document files
                    documents_dir = "data/documents"
                    found_content = []
                    
                    if os.path.exists(documents_dir):
                        for filename in os.listdir(documents_dir):
                            if filename.endswith('.txt'):
                                filepath = os.path.join(documents_dir, filename)
                                try:
                                    with open(filepath, 'r', encoding='utf-8') as f:
                                        content = f.read()
                                        # Simple keyword search (case insensitive)
                                        if re.search(topic, content, re.IGNORECASE):
                                            # Extract relevant section (first 500 chars containing the topic)
                                            lines = content.split('\\n')
                                            relevant_lines = []
                                            for line in lines:
                                                if re.search(topic, line, re.IGNORECASE):
                                                    # Get context around the matching line
                                                    idx = lines.index(line)
                                                    start_idx = max(0, idx - 2)
                                                    end_idx = min(len(lines), idx + 3)
                                                    relevant_lines.extend(lines[start_idx:end_idx])
                                                    break
                                            
                                            if relevant_lines:
                                                section = '\\n'.join(relevant_lines)
                                                found_content.append(f"From {filename}:\\n{section[:300]}...")
                                except Exception as e:
                                    self.logger.warning(f"Could not read {filename}: {e}")
                    
                    if found_content:
                        result = f"Found information about '{topic}':\\n\\n" + "\\n\\n".join(found_content[:3])  # Limit to 3 results
                        self.logger.info(f"✅ POLICY SEARCH: Found {len(found_content)} results for '{topic}'")
                        agent_logger.log_tool_call_result("search_policies", f"Found {len(found_content)} relevant documents", success=True)
                        return result
                    else:
                        result = f"No specific information found about '{topic}' in our policy documents. Please try different keywords or contact HR for assistance."
                        self.logger.info(f"❌ POLICY SEARCH: No results for '{topic}'")
                        agent_logger.log_tool_call_result("search_policies", "No relevant documents found", success=True)
                        return result
                
                except Exception as e:
                    error_msg = f"Error searching policies: {str(e)}"
                    self.logger.error(f"🚨 SEARCH ERROR: {error_msg}")
                    agent_logger.log_tool_call_result("search_policies", error_msg, success=False, error=str(e))
                    return error_msg
            
            tools.append(search_policies)
            self.logger.info("✅ Added search_policies tool")

        self.logger.info(f"Created {len(tools)} tools total: {[tool.name for tool in tools]}")
        return tools
    
    async def chat_completion(self, messages: List[Dict[str, Any]], **kwargs) -> AgentResponse:
        """Process chat using official LangChain agent with detailed logging."""
        from app.observability import agent_logger
        
        self._initialize()
        
        user_input = messages[-1]["content"]
        self.logger.info(f"🚀 CHAT START: Processing user query: '{user_input}'")
        agent_logger.log_tool_call_start("langchain_agent", {"user_input": user_input})
        
        try:
            self.logger.info("🤖 AGENT: Invoking LangChain agent with create_agent")
            
            # Use ainvoke for async as per official docs
            result = await self.agent.ainvoke({
                "messages": [{"role": "user", "content": user_input}]
            })
            
            self.logger.info(f"📦 AGENT RESULT: Raw result type={type(result)}")
            self.logger.info(f"📦 AGENT RESULT: Keys={list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
            
            # Debug: Print full result structure
            self.logger.info(f"🔍 DEBUG FULL RESULT: {json.dumps(str(result), indent=2)}")
            
            # Extract the final message content and tool calls
            final_messages = result.get("messages", [])
            self.logger.info(f"💬 MESSAGES: Found {len(final_messages)} messages in result")
            self.logger.info(f"💬 MESSAGES: Found {len(final_messages)} messages in result")
            
            # Track tool calls and content from messages
            tool_calls_made = []
            content = "No response generated"
            
            for i, message in enumerate(final_messages):
                message_type = type(message).__name__
                self.logger.info(f"📝 MESSAGE {i}: Type={message_type}")
                
                # Extract tool calls from AIMessage objects
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    self.logger.info(f"🔧 FOUND TOOL_CALLS in {message_type}: {message.tool_calls}")
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.get('name', 'unknown') if isinstance(tool_call, dict) else getattr(tool_call, 'name', 'unknown')
                        tool_args = tool_call.get('args', {}) if isinstance(tool_call, dict) else getattr(tool_call, 'args', {})
                        tool_id = tool_call.get('id', 'unknown') if isinstance(tool_call, dict) else getattr(tool_call, 'id', 'unknown')
                        
                        tool_calls_made.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "id": tool_id,
                            "success": True  # Assume success if we got this far
                        })
                        
                        self.logger.info(f"🔧 DETECTED TOOL CALL: {tool_name} with args: {tool_args}")
                        agent_logger.log_tool_call_result(tool_name, f"Called with args: {tool_args}", success=True)
                
                # Track ToolMessage responses 
                elif message_type == 'ToolMessage':
                    tool_content = getattr(message, 'content', '')
                    tool_call_id = getattr(message, 'tool_call_id', 'unknown')
                    self.logger.info(f"⚙️ TOOL RESPONSE: ID={tool_call_id}, Content='{tool_content}'")
                
                # Get final content from AI messages (prefer last non-empty content)
                elif message_type == 'AIMessage' and hasattr(message, 'content'):
                    if message.content and message.content.strip():
                        content = message.content
                        self.logger.info(f"💬 AI CONTENT: '{content[:100]}{'...' if len(content) > 100 else ''}'")
                
                # Also get content from human messages if needed
                elif message_type == 'HumanMessage' and not content.startswith("No response"):
                    if hasattr(message, 'content') and message.content:
                        self.logger.info(f"👤 HUMAN INPUT: '{message.content}'")
            
            self.logger.info(f"🛠️ TOTAL TOOL CALLS DETECTED: {len(tool_calls_made)}")
            for i, call in enumerate(tool_calls_made):
                self.logger.info(f"  {i+1}. {call['tool']} (ID: {call['id']})")
            
            if not tool_calls_made:
                self.logger.info("🔍 NO TOOL CALLS DETECTED: Agent responded without using tools")
            
            self.logger.info(f"✅ FINAL CONTENT: '{content[:200]}{'...' if len(content) > 200 else ''}'")
            
            response = AgentResponse(
                content=content,
                tool_calls=tool_calls_made,  # Now properly extracted from message chain
                metadata={"model": self.settings.llm.model_name}
            )
            
            self.logger.info(f"🎯 CHAT COMPLETE: Generated response with {len(content)} characters")
            agent_logger.log_tool_call_result("langchain_agent", f"Generated response ({len(content)} chars)", success=True)
            return response
            
        except Exception as e:
            self.logger.error(f"🚨 CHAT ERROR: Agent processing failed - {str(e)}")
            self.logger.error(f"🚨 ERROR TYPE: {type(e).__name__}")
            
            agent_logger.log_tool_call_result("langchain_agent", f"Error: {e}", success=False, error=str(e))
            
            return AgentResponse(
                content=f"Error: {e}",
                tool_calls=[],
                metadata={"error": str(e)},
                finish_reason="error"
            )


# Create instance
simple_agent = SimpleLangChainAgent()