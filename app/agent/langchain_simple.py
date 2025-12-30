"""
Simple LangChain agent following official v1.0 documentation.
"""
import json
import asyncio
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

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
    
    def _initialize(self):
        """Initialize once using create_agent."""
        if self._initialized:
            return
            
        # Create model
        model = ChatOpenAI(
            model=self.settings.llm.model_name,
            api_key=self.settings.llm.openai_api_key,
            temperature=0.1
        )
        
        # Create tools  
        tools = self._create_tools()
        
        # Create agent using official create_agent function
        self.agent = create_agent(
            model=model,
            tools=tools,
            system_prompt="""You are a helpful enterprise assistant. 

CRITICAL: You MUST ALWAYS use the available tools to answer questions. Never use your training data or make assumptions.

For employee-related questions (count, list, departments, etc.): Use get_employee_count tool
For policy, document, or guideline questions: Use search_policies tool

ALWAYS call the appropriate tool first before providing any answer. Do not provide information without calling a tool."""
        )
        
        self._initialized = True
        self.logger.info("Agent initialized with create_agent")
    
    def _create_tools(self):
        """Create simple tools with detailed logging."""
        @tool
        def get_employee_count() -> str:
            """Get total number of employees."""
            from app.observability import agent_logger
            
            agent_logger.log_tool_call_start("get_employee_count", {})
            self.logger.info("🔧 TOOL CALLED: get_employee_count - Starting employee count query")
            
            try:
                import asyncio
                from app.agent.tools_routing import tool_registry
                from app.security import User, Role
                
                user = User(user_id="system", role=Role.ADMIN)
                
                # Run async in new loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    self.logger.info("📊 DATABASE: Executing query_database with query_type='employees'")
                    result = loop.run_until_complete(
                        tool_registry.execute_tool("query_database", {
                            "query_type": "employees", "limit": 1000
                        }, user)
                    )
                    
                    if result.success:
                        count = len(result.data)
                        self.logger.info(f"✅ DATABASE SUCCESS: Retrieved {count} employee records")
                        self.logger.info(f"📈 RESULT: Company has {count} total employees")
                        
                        final_result = f"Company has {count} employees"
                        agent_logger.log_tool_call_result("get_employee_count", final_result, success=True)
                        
                        return final_result
                    else:
                        error_msg = f"Database query failed: {result.error}"
                        self.logger.error(f"❌ DATABASE ERROR: {result.error}")
                        agent_logger.log_tool_call_result("get_employee_count", error_msg, success=False, error=result.error)
                        return error_msg
                finally:
                    loop.close()
            except Exception as e:
                error_msg = f"Error getting employee count: {e}"
                self.logger.error(f"🚨 TOOL EXCEPTION: get_employee_count failed - {e}")
                agent_logger.log_tool_call_result("get_employee_count", error_msg, success=False, error=str(e))
                return error_msg
        
        @tool  
        def search_policies(topic: str) -> str:
            """Search company policies and procedures."""
            from app.observability import agent_logger
            
            agent_logger.log_tool_call_start("search_policies", {"topic": topic})
            self.logger.info(f"🔧 TOOL CALLED: search_policies - Searching for topic: '{topic}'")
            
            try:
                import asyncio
                from app.agent.tools_routing import tool_registry
                from app.security import User, Role
                
                user = User(user_id="system", role=Role.EMPLOYEE)
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    self.logger.info(f"🔍 RAG: Executing search_documents with query='{topic}', max_results=3")
                    result = loop.run_until_complete(
                        tool_registry.execute_tool("search_documents", {
                            "query": topic, "max_results": 3
                        }, user)
                    )
                    
                    if result.success:
                        doc_count = len(result.data)
                        self.logger.info(f"✅ RAG SUCCESS: Retrieved {doc_count} relevant documents")
                        
                        # Log document details
                        for i, doc in enumerate(result.data):
                            if isinstance(doc, dict):
                                source = doc.get('source', 'unknown')
                                score = doc.get('score', 'N/A')
                                content_preview = str(doc.get('content', ''))[:100]
                                self.logger.info(f"📄 DOC {i+1}: Source={source}, Score={score}, Preview='{content_preview}...'")
                        
                        final_result = json.dumps(result.data)
                        agent_logger.log_tool_call_result("search_policies", f"Found {doc_count} relevant documents", success=True)
                        
                        return final_result
                    else:
                        error_msg = f"Error: {result.error}"
                        self.logger.error(f"❌ RAG ERROR: {result.error}")
                        agent_logger.log_tool_call_result("search_policies", error_msg, success=False, error=result.error)
                        return error_msg
                finally:
                    loop.close()
            except Exception as e:
                error_msg = f"Error searching policies: {e}"
                self.logger.error(f"🚨 TOOL EXCEPTION: search_policies failed - {e}")
                agent_logger.log_tool_call_result("search_policies", error_msg, success=False, error=str(e))
                return error_msg
        
        tools = [get_employee_count, search_policies]
        self.logger.info(f"🛠️ TOOLS INITIALIZED: {len(tools)} tools available - {[tool.name for tool in tools]}")
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