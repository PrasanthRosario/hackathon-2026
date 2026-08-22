import React from 'react';
import { Loader2, CheckCircle2, XCircle, Wrench, Sparkles } from 'lucide-react';

// Shared result-view pieces (fix report card, flag panel, empty state) used by
// ValidateSimulateResultView -- the standalone Kit-render tab that used to
// live in this file has been retired in favor of the real Validate & Simulate
// (Isaac Sim) flow.

export function FixReportCard({ report, onApply, isApplying, onDismiss, applyLabel = 'Apply & Re-render' }) {
  const fixes = report.fixes || [];
  return (
    <div className="ph-card" style={{ padding: '16px', marginBottom: '16px', border: '1px solid var(--accent-orange)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
        <Sparkles size={16} style={{ color: 'var(--accent-orange)' }} />
        <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '14px', color: 'var(--text-main)' }}>
          Fix Report ({report.model_used || 'Sonnet'})
        </h3>
      </div>

      {report.summary && (
        <p style={{ fontSize: '13px', color: 'var(--text-main)', lineHeight: '1.6', marginBottom: '14px' }}>
          {report.summary}
        </p>
      )}

      {fixes.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '14px' }}>
          {fixes.map((f, i) => (
            <div key={i} style={{
              padding: '8px 12px',
              backgroundColor: '#0F172A',
              borderRadius: '6px',
              border: '1px solid var(--border-subtle)',
              fontSize: '12px'
            }}>
              <span className="ph-badge ph-badge-yellow" style={{ fontSize: '10px', marginRight: '8px' }}>
                {f.fix_type}
              </span>
              <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{f.target_id}</code>
              <div style={{ marginTop: '4px', color: 'var(--text-main)' }}>{f.rationale}</div>
            </div>
          ))}
        </div>
      ) : (
        <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '14px' }}>No fixes proposed.</p>
      )}

      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          className="ph-btn ph-btn-sm ph-btn-primary"
          onClick={onApply}
          disabled={isApplying || fixes.length === 0}
        >
          {isApplying ? <Loader2 size={13} className="animate-spin" /> : <Wrench size={13} />}
          {isApplying ? 'Applying & Re-verifying...' : applyLabel}
        </button>
        <button className="ph-btn ph-btn-sm" onClick={onDismiss} disabled={isApplying}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function FlagPanel({ title, empty, items }) {
  return (
    <div className="ph-card" style={{ padding: '14px' }}>
      <h4 style={{ fontFamily: 'var(--font-heading)', fontSize: '13px', marginBottom: '10px', color: 'var(--text-main)' }}>
        {title}
      </h4>
      {items.length === 0 ? (
        <p style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{empty}</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {items.map((item, i) => (
            <div key={i} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', fontSize: '12px' }}>
              {item.ok ? (
                <CheckCircle2 size={14} style={{ color: '#10B981', flexShrink: 0, marginTop: '2px' }} />
              ) : (
                <XCircle size={14} style={{ color: '#F87171', flexShrink: 0, marginTop: '2px' }} />
              )}
              <span style={{ color: 'var(--text-main)' }}>
                <code style={{ fontFamily: 'var(--font-mono)' }}>{item.label}</code>: {item.detail}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function EmptyState({ icon, title, detail, isError }) {
  return (
    <div style={{
      width: '100%',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      padding: '32px'
    }}>
      <div style={{ marginBottom: '14px' }}>{icon}</div>
      <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', color: isError ? '#F87171' : 'var(--text-main)', marginBottom: '8px' }}>
        {title}
      </h3>
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)', maxWidth: '420px', lineHeight: '1.6' }}>
        {detail}
      </p>
    </div>
  );
}
