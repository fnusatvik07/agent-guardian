"""
Simple LangChain agent following official v1.0 documentation.
"""
import json
import asyncio
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
            system_prompt="You are a helpful enterprise assistant. Use the available tools to answer questions accurately. Always use tools to get current data instead of guessing."
        )
        
        self._initialized = True
        self.logger.info("Agent initialized with create_agent")
    
    def _create_tools(self):
        """Create simple tools with detailed logging."""
        @tool
        def get_employee_count() -> str:
            """Get total number of employees."""
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
                        return f"Company has {count} employees"
                    else:
                        self.logger.error(f"❌ DATABASE ERROR: {result.error}")
                        return f"Error: {result.error}"
                finally:
                    loop.close()
            except Exception as e:
                self.logger.error(f"🚨 TOOL EXCEPTION: get_employee_count failed - {e}")
                return f"Error getting employee count: {e}"
        
        @tool  
        def search_policies(topic: str) -> str:
            """Search company policies and procedures."""
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
                        
                        return json.dumps(result.data)
                    else:
                        self.logger.error(f"❌ RAG ERROR: {result.error}")
                        return f"Error: {result.error}"
                finally:
                    loop.close()
            except Exception as e:
                self.logger.error(f"🚨 TOOL EXCEPTION: search_policies failed - {e}")
                return f"Error searching policies: {e}"
        
        tools = [get_employee_count, search_policies]
        self.logger.info(f"🛠️ TOOLS INITIALIZED: {len(tools)} tools available - {[tool.name for tool in tools]}")
        return tools
    
    async def chat_completion(self, messages: List[Dict[str, Any]], **kwargs) -> AgentResponse:
        """Process chat using official LangChain agent with detailed logging."""
        self._initialize()
        
        user_input = messages[-1]["content"]
        self.logger.info(f"🚀 CHAT START: Processing user query: '{user_input}'")
        
        try:
            self.logger.info("🤖 AGENT: Invoking LangChain agent with create_agent")
            
            # Use ainvoke for async as per official docs
            result = await self.agent.ainvoke({
                "messages": [{"role": "user", "content": user_input}]
            })
            
            self.logger.info(f"📦 AGENT RESULT: Raw result type={type(result)}")
            self.logger.info(f"📦 AGENT RESULT: Keys={list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
            
            # Extract the final message content
            final_messages = result.get("messages", [])
            self.logger.info(f"💬 MESSAGES: Found {len(final_messages)} messages in result")
            
            if final_messages:
                last_message = final_messages[-1]
                self.logger.info(f"📝 LAST MESSAGE: Type={type(last_message)}, Has content={hasattr(last_message, 'content')}")
                
                content = last_message.content if hasattr(last_message, 'content') else str(last_message)
                self.logger.info(f"✅ FINAL CONTENT: '{content[:200]}{'...' if len(content) > 200 else ''}'")
            else:
                content = "No response generated"
                self.logger.warning("⚠️ NO MESSAGES: Agent returned empty messages list")
            
            response = AgentResponse(
                content=content,
                tool_calls=[],
                metadata={"model": self.settings.llm.model_name}
            )
            
            self.logger.info(f"🎯 CHAT COMPLETE: Generated response with {len(content)} characters")
            return response
            
        except Exception as e:
            self.logger.error(f"🚨 CHAT ERROR: Agent processing failed - {str(e)}")
            self.logger.error(f"🚨 ERROR TYPE: {type(e).__name__}")
            
            return AgentResponse(
                content=f"Error: {e}",
                tool_calls=[],
                metadata={"error": str(e)},
                finish_reason="error"
            )


# Create instance
simple_agent = SimpleLangChainAgent()