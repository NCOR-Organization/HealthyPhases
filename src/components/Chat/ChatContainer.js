import React, { useState, useCallback, useEffect } from 'react';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import ModeSelector from './ModeSelector';
import styles from './Chat.module.css';
import ExecutionEnvironment from '@docusaurus/ExecutionEnvironment';
import { generateResponse } from '../../../api';

function ChatContainer() {
  console.log('ChatContainer is rendering');
  
  const [messages, setMessages] = useState(() => {
    if (ExecutionEnvironment.canUseDOM) {
      const savedMessages = localStorage.getItem('chatMessages');
      if (savedMessages) {
        return JSON.parse(savedMessages);
      }
    }
    return [];
  });

  const [mode, setMode] = useState('test'); // Default to test mode
  const [isLoading, setIsLoading] = useState(false);

  const showLoadingAndGreeting = useCallback(() => {
    // Clear existing messages first
    setMessages([{
      id: 'loading',
      content: "...",
      timestamp: new Date().toISOString(),
      role: 'assistant',
    }]);

    setTimeout(() => {
      const greetingMessage = {
        id: 'initial-greeting',
        content: "Hi, ici Bob, comment puis-je vous aider ?\n\n**Available Intentions:**\n1. **@ontology** - Access knowledge base\n2. **@chatgpt** - Use ChatGPT integration\n3. **@perplexity** - Web search capabilities\n4. **@support** - Get help and support\n\n*For specific Forvis Mazars information, I have detailed data about leadership, official mission, projects, and more. Let me know what you'd like to explore!*\n\n**Sample Table:**\n\n| Date | Ouverture | Haut | Bas | Clôture | Volume |\n|------|-----------|------|-----|---------|--------|\n| 01-10-2023 | 250.00 € | 252.50 € | 248.00 € | 251.00 € | 3,200,000 |\n| 02-10-2023 | 251.00 € | 253.00 € | 250.00 € | 252.50 € | 3,500,000 |\n| 03-10-2023 | 252.50 € | 255.00 € | 251.50 € | 254.00 € | 4,100,000 |",
        timestamp: new Date().toISOString(),
        role: 'assistant',
      };
      setMessages([greetingMessage]);
    }, 1500);
  }, []);

  useEffect(() => {
    if (!ExecutionEnvironment.canUseDOM) return;
    
    console.log('ChatContainer mounted');
    if (messages.length === 0) {
      showLoadingAndGreeting();
    }
  }, []); 

  useEffect(() => {
    if (!ExecutionEnvironment.canUseDOM) return;

    console.log('Messages updated:', messages);
    localStorage.setItem('chatMessages', JSON.stringify(messages));
  }, [messages]);

  const handleTestModeResponse = (content) => {
    return new Promise((resolve) => {
      setTimeout(() => {
        if (content.toLowerCase().includes('table')) {
          resolve(`Here's a test table:\n\n| Name | Age | City |\n|------|-----|------|\n| John | 25 | Paris |\n| Jane | 30 | London |\n| Bob | 35 | Berlin |`);
        } else {
          resolve('This is a test mode response. The AI is simulated. Try asking for a "table" to see table rendering.');
        }
      }, 1000);
    });
  };

  const handleSendMessage = useCallback(async (content) => {
    if (!ExecutionEnvironment.canUseDOM) return;

    console.log('Sending message:', content);
    const newMessage = {
      id: Date.now().toString(),
      content,
      timestamp: new Date().toISOString(),
      role: 'user',
    };
    setMessages(prev => [...prev, newMessage]);
    
    // Add typing animation message using the same format as initial loading
    const typingMessage = {
      id: 'typing-' + Date.now(),
      content: '...',
      timestamp: new Date().toISOString(),
      role: 'assistant',
      isTyping: true,
    };
    setMessages(prev => [...prev, typingMessage]);
    
    setIsLoading(true);
    try {
      const response = mode === 'test' 
        ? await handleTestModeResponse(content)
        : await generateResponse(content);

      // Remove typing message and add real response
      setMessages(prev => prev.filter(msg => !msg.isTyping));
      
      const assistantMessage = {
        id: (Date.now() + 1).toString(),
        content: response,
        timestamp: new Date().toISOString(),
        role: 'assistant',
      };
      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Error getting response:', error);
      
      // Remove typing message
      setMessages(prev => prev.filter(msg => !msg.isTyping));
      
      const errorMessage = {
        id: (Date.now() + 1).toString(),
        content: error.message.includes('API key') 
          ? 'Naas API authentication failed. Please check your credentials or switch to Test Mode.'
          : 'I apologize, but I encountered an error. Please try again.',
        timestamp: new Date().toISOString(),
        role: 'assistant',
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  }, [mode]);

  const handleClearChat = useCallback(() => {
    if (!ExecutionEnvironment.canUseDOM) return;

    console.log('Clearing chat');
    showLoadingAndGreeting();
    localStorage.clear();
  }, [showLoadingAndGreeting]);

  const handleReload = useCallback(() => {
    showLoadingAndGreeting();
  }, [showLoadingAndGreeting]);

  const handleModeChange = useCallback((newMode) => {
    setMode(newMode);
    handleClearChat(); // Clear chat when mode changes
  }, [handleClearChat]);

  return (
    <div className={styles.chatWrapper}>
      <div className={styles.container}>
        <div className={styles.scrollContainer}>
          <MessageList messages={messages} />
        </div>
        <div className={styles.inputContainer}>
          <ChatInput onSendMessage={handleSendMessage} disabled={isLoading} />
          <div className={styles.buttonGroup}>
            <button 
              onClick={handleReload} 
              className={styles.reloadButton}
              disabled={isLoading}
            >
              Reload Chat
            </button>
            <ModeSelector mode={mode} onModeChange={handleModeChange} />
            <button
              onClick={handleClearChat}
              className={styles.clearButton}
              disabled={isLoading}
              aria-label="Clear chat history"
            >
              <span className={styles.clearText}>Clear History</span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M3 6h18" />
                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
              </svg>
            </button>
          </div>
          <p className={styles.disclaimer}>
            AI doesn't replace your judgment. You're accountable for its use.
          </p>
        </div>
      </div>
    </div>
  );
}

export default ChatContainer; 