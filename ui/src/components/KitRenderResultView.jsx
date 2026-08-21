import React from 'react';
import { Loader2, AlertTriangle, ImageOff, CheckCircle2, XCircle, Wrench } from 'lucide-react';

export default function KitRenderResultView({ status, result, error, onProposeFix, isFixing }) {
  if (status === 'idle') {
    return (
      <EmptyState
        icon={<ImageOff size={36} style={{ color: 'var(--text-muted)' }} />}
        title="No Kit render yet"
        detail="Generate a USD stage, then click 'Render in Kit' above to invoke kit_render_worker.py and see real render/physics/coverage output here."
      />
    );
  }

  if (status === 'rendering') {
    return (
      <EmptyState
        icon={<Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-orange)' }} />}
        title="Rendering in Kit..."
        detail="Invoking kit_render_worker.py via subprocess. This runs RTX render, PhysX stability check, and frustum coverage check per camera."
      />
    );
  }

  if (status === 'failed') {
    return (
      <EmptyState
        icon={<AlertTriangle size={36} style={{ color: '#F87171' }} />}
        title="Kit render failed"
        detail={error || 'Unknown error. Check backend logs / render.log for details.'}
        isError
      />
    );
  }

  if (!result) {
    return null;
  }

  const renderFiles = result.render_files || [];
  const coverageFlags = result.coverage_flags || [];
  const physicsFlags = result.physics_flags || [];
  const unstableCount = physicsFlags.filter((f) => !f.stable).length;
  const hasIssues = coverageFlags.length > 0 || unstableCount > 0;

  return (
    <div style={{ width: '100%', height: '100%', overflowY: 'auto', padding: '20px' }}>
      {hasIssues && onProposeFix && (
        <div className="ph-card" style={{
          padding: '12px 16px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          border: '1px solid var(--border-accent)'
        }}>
          <span style={{ fontSize: '12.5px', color: 'var(--text-main)' }}>
            {coverageFlags.length} coverage flag(s), {unstableCount} physics flag(s) detected.
          </span>
          <button
            className="ph-btn ph-btn-sm ph-btn-yellow"
            onClick={onProposeFix}
            disabled={isFixing}
          >
            {isFixing ? <Loader2 size={13} className="animate-spin" /> : <Wrench size={13} />}
            {isFixing ? 'Fixing & Re-verifying...' : 'Propose Fix & Re-verify'}
          </button>
        </div>
      )}

      {/* Render Images Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '14px', marginBottom: '20px' }}>
        {renderFiles.map((src, i) => (
          <div key={i} className="ph-card" style={{ overflow: 'hidden', padding: 0 }}>
            <img
              src={src}
              alt={src}
              style={{ width: '100%', display: 'block', aspectRatio: '16 / 9', objectFit: 'cover', backgroundColor: '#0F172A' }}
            />
            <div style={{
              padding: '6px 10px',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-muted)',
              borderTop: '1px solid var(--border-subtle)'
            }}>
              {src.split('/').pop()}
            </div>
          </div>
        ))}
      </div>

      {/* Flags */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
        <FlagPanel
          title={`Coverage Flags (${coverageFlags.length})`}
          empty="No coverage gaps flagged."
          items={coverageFlags.map((f) => ({
            ok: false,
            label: f.shot_id,
            detail: `${f.edge} — ${f.gap_degrees}° gap at frame ${f.frame}`,
          }))}
        />
        <FlagPanel
          title={`Physics Flags (${physicsFlags.length})`}
          empty="No physics instability flagged."
          items={physicsFlags.map((f) => ({
            ok: f.stable,
            label: f.prim_id,
            detail: f.detail,
          }))}
        />
      </div>
    </div>
  );
}

function FlagPanel({ title, empty, items }) {
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

function EmptyState({ icon, title, detail, isError }) {
  return (
    <div style={{
      width: '100%',
      height: '100%',
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
