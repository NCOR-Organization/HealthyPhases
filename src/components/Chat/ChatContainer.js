import React, { useState, useCallback, useEffect, useRef } from 'react';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import styles from './Chat.module.css';
import ExecutionEnvironment from '@docusaurus/ExecutionEnvironment';
import { generateResponse } from '../../../api';

function ChatContainer() {
  console.log('ChatContainer is rendering');
  
  const scrollContainerRef = useRef(null);
  
  const [messages, setMessages] = useState(() => {
    if (ExecutionEnvironment.canUseDOM) {
      const savedMessages = localStorage.getItem('chatMessages');
      if (savedMessages) {
        return JSON.parse(savedMessages);
      }
    }
    return [];
  });

  const [isLoading, setIsLoading] = useState(false);

  const scrollToBottom = useCallback(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, []);

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
        content: "Hi, I'm ELO, the experimental AI for the HealthyPhases Project. How can I help you today?",
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
    
    // Auto-scroll to bottom when messages change
    setTimeout(() => {
      scrollToBottom();
    }, 100); // Small delay to ensure DOM is updated
  }, [messages, scrollToBottom]);

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
      const response = await generateResponse(content);

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
        content: 'I apologize, but I encountered an error. Please try again.',
        timestamp: new Date().toISOString(),
        role: 'assistant',
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleClearChat = useCallback(() => {
    if (!ExecutionEnvironment.canUseDOM) return;

    console.log('Clearing chat');
    showLoadingAndGreeting();
    localStorage.clear();
  }, [showLoadingAndGreeting]);

  const handleReload = useCallback(() => {
    showLoadingAndGreeting();
  }, [showLoadingAndGreeting]);

  return (
    <div className={styles.chatWrapper}>
      <div className={styles.container}>
        <div className={styles.scrollContainer} ref={scrollContainerRef}>
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