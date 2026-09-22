import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage } from '../types';

const AgentChat: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMessage: ChatMessage = {
      role: 'user',
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      // Simulate agent response (in a real implementation, this would call the backend)
      // For now, we'll provide helpful guidance since the agent endpoint may need to be implemented

      setTimeout(() => {
        const assistantMessage: ChatMessage = {
          role: 'assistant',
          content: `I received your message: "${input}"\n\nNote: This is a demo frontend. To enable full AI agent functionality, you'll need to:\n\n1. Implement an agent chat endpoint in your FastAPI backend\n2. Connect it to the TaskAgent class in agent/agent.py\n3. Return structured responses with task operations\n\nExample commands you could try:\n- "Create a task called 'Review PR'\n- "List all high priority tasks"\n- "Mark task t_xxx as done"\n- "What tasks are due this week?"`,
          timestamp: new Date(),
          metadata: {
            iterations: 1,
            tool_calls: 0,
            status: 'completed',
          },
        };

        setMessages((prev) => [...prev, assistantMessage]);
        setLoading(false);
      }, 1000);
    } catch (error) {
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: 'Sorry, I encountered an error processing your request.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const exampleCommands = [
    'Create 3 tasks for project kickoff',
    'List all high priority tasks',
    'Show tasks due this week',
    'Move urgent tasks to in progress',
  ];

  return (
    <div className="agent-chat">
      <div className="chat-header">
        <h2>AI Agent Chat</h2>
        <p>Ask the agent to manage tasks using natural language</p>
      </div>

      {messages.length === 0 && (
        <div className="chat-welcome">
          <h3>Welcome to Task Agent!</h3>
          <p>Try these example commands:</p>
          <div className="example-commands">
            {exampleCommands.map((cmd, idx) => (
              <button
                key={idx}
                onClick={() => setInput(cmd)}
                className="example-btn"
              >
                {cmd}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message message-${msg.role}`}>
            <div className="message-header">
              <strong>{msg.role === 'user' ? 'You' : 'Agent'}</strong>
              <span className="message-time">
                {msg.timestamp.toLocaleTimeString()}
              </span>
            </div>
            <div className="message-content">{msg.content}</div>
            {msg.metadata && (
              <div className="message-metadata">
                {msg.metadata.iterations && (
                  <span>Iterations: {msg.metadata.iterations}</span>
                )}
                {msg.metadata.tool_calls !== undefined && (
                  <span>Tool Calls: {msg.metadata.tool_calls}</span>
                )}
                {msg.metadata.status && (
                  <span className={`status-${msg.metadata.status}`}>
                    Status: {msg.metadata.status}
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="message message-assistant">
            <div className="message-header">
              <strong>Agent</strong>
            </div>
            <div className="message-content loading-dots">
              <span>.</span><span>.</span><span>.</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask the agent to manage tasks... (Press Enter to send)"
          rows={2}
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="btn btn-primary"
        >
          Send
        </button>
      </div>
    </div>
  );
};

export default AgentChat;
