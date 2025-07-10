import React, { memo, useEffect } from 'react';
import PropTypes from 'prop-types';
import Link from '@docusaurus/Link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import styles from './Chat.module.css';

const Message = memo(function Message({ role, content, isTyping }) {
  const isUser = role === 'user';
  console.log('Message rendering:', { role, content, isTyping });

  const renderContent = (text) => {
    // For user messages, keep the simple link rendering
    if (isUser) {
      // Regular expression to match markdown links: [text](url)
      const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
      const parts = [];
      let lastIndex = 0;
      let match;

      while ((match = linkRegex.exec(text)) !== null) {
        // Add text before the link
        if (match.index > lastIndex) {
          parts.push(text.slice(lastIndex, match.index));
        }
        // Add the link component
        parts.push(
          <Link key={match.index} to={match[2]}>
            {match[1]}
          </Link>
        );
        lastIndex = match.index + match[0].length;
      }
      // Add remaining text after last link
      if (lastIndex < text.length) {
        parts.push(text.slice(lastIndex));
      }
      return parts.length > 0 ? parts : text;
    }

    // For assistant messages, use React Markdown for full markdown rendering
    try {
      return (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // Customize link rendering to use Docusaurus Link
            a: ({ href, children }) => {
              if (href && href.startsWith('/')) {
                return <Link to={href}>{children}</Link>;
              }
              return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
            },
            // Customize list rendering for better spacing
            ul: ({ children }) => <ul style={{ margin: '0.5rem 0', paddingLeft: '1.5rem' }}>{children}</ul>,
            ol: ({ children }) => <ol style={{ margin: '0.5rem 0', paddingLeft: '1.5rem' }}>{children}</ol>,
            li: ({ children }) => <li style={{ margin: '0.25rem 0' }}>{children}</li>,
            // Customize paragraph rendering
            p: ({ children }) => <p style={{ margin: '0.5rem 0' }}>{children}</p>,
            // Customize heading rendering
            h1: ({ children }) => <h1 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: '1rem 0 0.5rem 0' }}>{children}</h1>,
            h2: ({ children }) => <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', margin: '0.75rem 0 0.5rem 0' }}>{children}</h2>,
            h3: ({ children }) => <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', margin: '0.5rem 0 0.25rem 0' }}>{children}</h3>,
            // Customize table rendering
            table: ({ children }) => (
              <div style={{
                width: '100%',
                overflowX: 'auto',
                margin: '1rem 0'
              }}>
                <table className={styles.markdownTable}>
                  {children}
                </table>
              </div>
            ),
            thead: ({ children }) => <thead style={{ backgroundColor: '#f9fafb' }}>{children}</thead>,
            tbody: ({ children }) => <tbody>{children}</tbody>,
            tr: ({ children }) => <tr style={{ borderBottom: '1px solid #e5e7eb' }}>{children}</tr>,
            th: ({ children }) => (
              <th style={{
                padding: '0.75rem',
                textAlign: 'left',
                fontWeight: '600',
                color: '#374151',
                borderBottom: '2px solid #e5e7eb'
              }}>
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td style={{
                padding: '0.75rem',
                textAlign: 'left',
                color: '#374151',
                borderBottom: '1px solid #f3f4f6'
              }}>
                {children}
              </td>
            ),
            // Customize code rendering
            code: ({ children, className }) => {
              if (className) {
                // Inline code
                return <code style={{ 
                  backgroundColor: '#f1f5f9', 
                  padding: '0.125rem 0.25rem', 
                  borderRadius: '0.25rem',
                  fontSize: '0.875rem',
                  fontFamily: 'monospace'
                }}>{children}</code>;
              }
              return <code>{children}</code>;
            },
            pre: ({ children }) => <pre style={{ 
              backgroundColor: '#f8fafc', 
              padding: '1rem', 
              borderRadius: '0.5rem',
              overflow: 'auto',
              margin: '0.5rem 0'
            }}>{children}</pre>,
            // Customize blockquote rendering
            blockquote: ({ children }) => <blockquote style={{ 
              borderLeft: '4px solid #e5e7eb', 
              paddingLeft: '1rem', 
              margin: '0.5rem 0',
              fontStyle: 'italic',
              color: '#6b7280'
            }}>{children}</blockquote>,
          }}
        >
          {text}
        </ReactMarkdown>
      );
    } catch (error) {
      console.error('Error rendering markdown:', error);
      // Fallback to plain text if markdown rendering fails
      return <div>{text}</div>;
    }
  };

  return (
    <div className={`${styles.messageGroup} ${isUser ? styles.user : styles.assistant}`}>
      <div className={styles.messageWrapper}>
        <div className={`${styles.avatar} ${isUser ? styles.user : styles.assistant}`}>
          {isUser ? 'U' : (
            <img 
              src="img/ELO.png" 
              alt="ELO Avatar" 
              className={styles.avatarImage}
              onError={(e) => console.error('Image failed to load:', e)}
            />
          )}
        </div>
        <div className={styles.messageContent}>
          {(content === '...' || isTyping) ? (
            <div className={styles.typingIndicator}>
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </div>
          ) : (
            renderContent(content)
          )}
        </div>
      </div>
    </div>
  );
});

Message.propTypes = {
  role: PropTypes.oneOf(['user', 'assistant']).isRequired,
  content: PropTypes.string.isRequired,
  isTyping: PropTypes.bool
};

function MessageList({ messages }) {
  useEffect(() => {
    console.log('MessageList received messages:', messages);
  }, [messages]);

  return (
    <div className={styles.messageContainer}>
      {messages.map(({ id, role, content, isTyping }) => {
        console.log('Rendering message:', { id, role, content, isTyping });
        return (
          <Message 
            key={id} 
            role={role} 
            content={content} 
            isTyping={isTyping}
          />
        );
      })}
    </div>
  );
}

MessageList.propTypes = {
  messages: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.string.isRequired,
      role: PropTypes.oneOf(['user', 'assistant']).isRequired,
      content: PropTypes.string.isRequired,
      timestamp: PropTypes.string,
      isTyping: PropTypes.bool
    })
  ).isRequired
};

export default memo(MessageList);