import React, { useState, useRef, useEffect } from 'react';
import { Download, Cpu } from 'lucide-react';

function getModelLabel(modelUsed) {
  if (!modelUsed) return null;
  if (modelUsed.includes('deterministic')) return 'Local Agent';
  if (modelUsed === 'usd-script-agent') return 'USD Agent';
  if (modelUsed === 'deterministic-fallback') return 'Fallback';
  if (modelUsed.includes('haiku')) return 'Haiku';
  if (modelUsed.includes('sonnet')) return 'Sonnet';
  if (modelUsed.includes('opus')) return 'Opus';
  if (modelUsed === 'error') return 'Error';
  return 'Off Frame Agent';
}

export default function LeftPanel({
  messages,
  onSendMessage,
  isLoading,
  isDownloadingPromptUSD,
}) {
  const [inputText, setInputText] = useState('');
  const chatBottomRef = useRef(null);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!inputText.trim() || isLoading) return;
    onSendMessage(inputText.trim());
    setInputText('');
  };

  const handleQuickPrompt = (prompt) => {
    if (isLoading) return;
    onSendMessage(prompt);
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      backgroundColor: 'var(--bg-surface)',
      borderRight: '1px solid var(--border-light)',
      overflow: 'hidden'
    }}>
      {/* Panel Top Header */}
      <div style={{
        padding: '14px 20px',
        backgroundColor: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-light)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            background: 'rgba(241, 168, 10, 0.15)',
            border: '1px solid rgba(241, 168, 10, 0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '16px'
          }}>
            💬
          </div>
          <div>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '15px', fontWeight: 700, color: 'var(--text-main)' }}>
              Set Assistant
            </h2>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
              Describe a set -- generates a downloadable USD file
            </p>
          </div>
        </div>

        <div className="ph-badge ph-badge-grey">
          <span>FASTAPI BACKEND</span>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}>
        {messages.map((msg, idx) => (
          <div
            key={idx}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: '88%'
            }}
          >
            {/* Sender / Model Badge */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              marginBottom: '4px',
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start'
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>
                {msg.role === 'user' ? 'DIRECTOR' : 'OFF FRAME AGENT'}
              </span>
              {msg.model_used && (
                <span className="ph-badge ph-badge-orange" style={{ fontSize: '9px', padding: '1px 6px' }}>
                  {getModelLabel(msg.model_used)}
                </span>
              )}
            </div>

            {/* Bubble Content */}
            <div style={{
              padding: '12px 16px',
              backgroundColor: msg.role === 'user' ? 'var(--accent-orange)' : 'var(--bg-surface-elevated)',
              color: msg.role === 'user' ? '#FFFFFF' : 'var(--text-main)',
              border: '1px solid',
              borderColor: msg.role === 'user' ? 'rgba(245, 78, 0, 0.4)' : 'var(--border-subtle)',
              borderRadius: msg.role === 'user' ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
              fontSize: '13.5px',
              lineHeight: '1.6',
              boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
            }}>
              {msg.content}
            </div>
          </div>
        ))}

        {/* Loading Indicator */}
        {isLoading && (
          <div style={{ alignSelf: 'flex-start', maxWidth: '80%' }}>
            <div style={{
              padding: '10px 14px',
              backgroundColor: 'var(--bg-surface-elevated)',
              borderRadius: '10px',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-muted)'
            }}>
              <Cpu size={14} className="animate-spin" style={{ color: 'var(--accent-orange)' }} />
              <span>{isDownloadingPromptUSD ? 'Generating downloadable USD...' : 'Sending request to backend...'}</span>
            </div>
          </div>
        )}

        <div ref={chatBottomRef} />
      </div>

      {/* Quick Prompt Recommendation Chips */}
      <div style={{
        padding: '10px 16px',
        backgroundColor: 'var(--bg-surface-elevated)',
        borderTop: '1px solid var(--border-light)',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        overflowX: 'auto'
      }}>
        <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
          Quick Prompts:
        </span>
        <button
          className="ph-btn ph-btn-sm"
          style={{ whiteSpace: 'nowrap', fontSize: '11.5px', padding: '3px 10px' }}
          onClick={() => handleQuickPrompt('Create a cooking show kitchen set')}
        >
          Cooking Show Kitchen
        </button>
        <button
          className="ph-btn ph-btn-sm"
          style={{ whiteSpace: 'nowrap', fontSize: '11.5px', padding: '3px 10px' }}
          onClick={() => handleQuickPrompt('Create a podcast studio room with two chairs and microphones')}
        >
          Podcast Studio
        </button>
        <button
          className="ph-btn ph-btn-sm"
          style={{ whiteSpace: 'nowrap', fontSize: '11.5px', padding: '3px 10px' }}
          onClick={() => handleQuickPrompt('Create a church set with a crowd outside')}
        >
          Church Exterior
        </button>
      </div>

      {/* Chat Input Bar */}
      <form onSubmit={handleSubmit} style={{
        padding: '14px 16px',
        backgroundColor: 'var(--bg-surface)',
        borderTop: '1px solid var(--border-light)',
        display: 'flex',
        gap: '10px'
      }}>
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder="Describe USD scene to generate and download..."
          disabled={isLoading}
          style={{
            flex: 1,
            padding: '10px 16px',
            backgroundColor: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '8px',
            fontFamily: 'var(--font-body)',
            fontSize: '13.5px',
            color: 'var(--text-main)',
            outline: 'none'
          }}
        />
        <button
          type="submit"
          disabled={isLoading || !inputText.trim()}
          className="ph-btn ph-btn-primary"
          style={{ padding: '0 18px' }}
        >
          <Download size={16} />
        </button>
      </form>
    </div>
  );
}
