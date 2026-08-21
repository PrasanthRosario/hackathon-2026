import React, { useState, useRef, useEffect } from 'react';
import { Send, CheckCircle2, Cpu, Sparkles, Box, ChevronDown, ChevronUp, Download } from 'lucide-react';

function getModelLabel(modelUsed) {
  if (!modelUsed) return null;
  if (modelUsed.includes('deterministic')) return 'Local Agent';
  if (modelUsed.includes('haiku')) return 'Haiku';
  if (modelUsed.includes('sonnet')) return 'Sonnet';
  if (modelUsed.includes('opus')) return 'Opus';
  if (modelUsed === 'error') return 'Error';
  if (modelUsed === 'preset') return 'Preset';
  return 'Offset Agent';
}

export default function LeftPanel({
  messages,
  onSendMessage,
  isLoading,
  sceneConfig,
  readableSummary,
  readyForConfirmation,
  onConfirmGenerateUSD,
  isGeneratingUSD,
  isDownloadingPromptUSD,
  onDownloadPromptUSD,
  usdStatus,
  onCheckCoverage,
  onCheckPhysics,
  checkResults
}) {
  const [inputText, setInputText] = useState('');
  const [showAdvancedTools, setShowAdvancedTools] = useState(false);
  const chatBottomRef = useRef(null);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, readyForConfirmation]);

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

  const handleDownloadPromptUSD = () => {
    if (!inputText.trim() || isLoading || isDownloadingPromptUSD) return;
    onDownloadPromptUSD(inputText.trim());
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
              Scene operation chat flow
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
                {msg.role === 'user' ? 'DIRECTOR' : 'OFFSET AGENT'}
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
              <span>Sending scene request to backend...</span>
            </div>
          </div>
        )}

        {/* READABLE SCENE SUMMARY CARD (Shown ONLY when scene extraction completes) */}
        {readyForConfirmation && sceneConfig && (
          <div className="ph-card" style={{
            padding: '18px',
            backgroundColor: '#131B2A',
            marginTop: '8px',
            border: '1px solid var(--border-accent)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={19} style={{ color: 'var(--accent-orange)' }} />
                <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '15px', fontWeight: 700, color: '#FFF' }}>
                  Extracted Set Configuration
                </h3>
              </div>
              <span className="ph-badge ph-badge-yellow">CONFIRMATION READY</span>
            </div>

            {/* Formatted Readable Parameters Summary */}
            <div style={{
              backgroundColor: '#0F172A',
              padding: '14px',
              borderRadius: '8px',
              border: '1px solid var(--border-subtle)',
              fontSize: '12.5px',
              fontFamily: 'var(--font-mono)',
              marginBottom: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#38BDF8' }}>
                <Box size={14} />
                <span>Floor Space: <strong>{sceneConfig.floor?.width}m (Width) × {sceneConfig.floor?.depth}m (Depth)</strong></span>
              </div>

              {sceneConfig.walls && sceneConfig.walls.length > 0 && (
                <div>
                  <strong style={{ color: '#F1A80A' }}>🧱 Walls ({sceneConfig.walls.length}):</strong>
                  <ul style={{ paddingLeft: '18px', marginTop: '4px', color: '#E2E8F0', lineHeight: '1.7' }}>
                    {sceneConfig.walls.map((w, i) => (
                      <li key={i}>
                        <code>{w.id}</code>: {w.width}m wide × {w.height}m high at [{w.position.join(', ')}] ({w.rotation}°)
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {sceneConfig.shots && sceneConfig.shots.length > 0 && (
                <div>
                  <strong style={{ color: '#FF7A38' }}>🎥 Shots ({sceneConfig.shots.length}):</strong>
                  <ul style={{ paddingLeft: '18px', marginTop: '4px', color: '#E2E8F0', lineHeight: '1.7' }}>
                    {sceneConfig.shots.map((s, i) => (
                      <li key={i}>
                        <code>{s.shot_id}</code>: Lens {s.focal_length_mm}mm | Dolly [{s.start_position.join(', ')}] ➔ [{s.end_position.join(', ')}] ({s.duration_seconds}s)
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Confirm & Generate USD Action Button */}
            <button
              className="ph-btn ph-btn-primary"
              style={{ width: '100%', padding: '11px 18px', fontSize: '14px' }}
              onClick={onConfirmGenerateUSD}
              disabled={isGeneratingUSD}
            >
              <Sparkles size={16} />
              {isGeneratingUSD ? 'Generating USD Stage...' : 'Confirm & Generate USD Stage'}
            </button>

            {/* Optional Collapsible Advanced Validation Suite */}
            <div style={{ marginTop: '14px', paddingTop: '10px', borderTop: '1px dashed var(--border-subtle)' }}>
              <button
                className="ph-btn ph-btn-sm"
                onClick={() => setShowAdvancedTools(!showAdvancedTools)}
                style={{ width: '100%', justifyContent: 'space-between', color: 'var(--text-muted)' }}
              >
                <span>Advanced Validation Suite</span>
                {showAdvancedTools ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>

              {showAdvancedTools && (
                <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                    <button className="ph-btn ph-btn-sm" onClick={onCheckCoverage}>
                      Frustum Coverage
                    </button>
                    <button className="ph-btn ph-btn-sm" onClick={onCheckPhysics}>
                      Physics Clearance
                    </button>
                  </div>
                  <p style={{ fontSize: '10.5px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', margin: 0 }}>
                    Fast heuristic checks only. For real render/physics/coverage validation and fix
                    verification, use "Render in Kit" in the viewport panel →
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Validation Results Display */}
        {checkResults && (
          <div className="ph-card" style={{ padding: '12px', backgroundColor: '#0F172A', color: '#7DD3FC', fontSize: '11.5px', fontFamily: 'var(--font-mono)' }}>
            <strong>Validation Output:</strong>
            <pre style={{ marginTop: '6px', whiteSpace: 'pre-wrap' }}>{JSON.stringify(checkResults, null, 2)}</pre>
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
          onClick={() => handleQuickPrompt('2 walls forming a corner, 4m wide back wall, 3m side wall, floor and 3m ceiling, table and chair inside.')}
        >
          2-Wall Corner Set
        </button>
        <button
          className="ph-btn ph-btn-sm"
          style={{ whiteSpace: 'nowrap', fontSize: '11.5px', padding: '3px 10px' }}
          onClick={() => handleQuickPrompt('Bedroom set with 3 walls, 4m back wall, 3m side walls, dolly track left to right.')}
        >
          Bedroom 3-Wall
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
          placeholder="Describe set (e.g. 2 walls, floor and ceiling, table and chair)..."
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
          <Send size={16} />
        </button>
        <button
          type="button"
          disabled={isLoading || isDownloadingPromptUSD || !inputText.trim()}
          className="ph-btn ph-btn-yellow"
          style={{ padding: '0 14px' }}
          onClick={handleDownloadPromptUSD}
          title="Generate and download USD from prompt"
        >
          <Download size={16} />
          <span style={{ fontSize: '11.5px' }}>
            {isDownloadingPromptUSD ? 'USD...' : 'USD'}
          </span>
        </button>
      </form>
    </div>
  );
}
