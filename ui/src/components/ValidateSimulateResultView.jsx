import React, { useEffect, useState } from 'react';
import { Loader2, ShieldCheck, ShieldAlert, ShieldX, RefreshCw } from 'lucide-react';
import { EmptyState, FlagPanel, FixReportCard } from './KitRenderResultView';

function formatElapsed(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export default function ValidateSimulateResultView({
  status,
  job,
  result,
  error,
  onCheckStatusNow,
  onGenerateFixReport,
  isGeneratingReport,
  fixReport,
  onApplyFixReport,
  isApplyingFix,
  onDismissFixReport,
}) {
  // Ticks once a second purely to re-render the elapsed-time readout below --
  // the actual status polling (every 5s) lives in App.jsx, this is just the
  // clock display so a 10+ minute wait doesn't look frozen.
  const [, forceTick] = useState(0);
  useEffect(() => {
    if (status !== 'queued' && status !== 'running') return undefined;
    const id = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [status]);

  if (status === 'idle' || !status) {
    return (
      <div style={{ width: '100%', height: '100%', overflowY: 'auto', padding: '20px' }}>
        <EmptyState
          icon={<ShieldCheck size={36} style={{ color: 'var(--text-muted)' }} />}
          title="No Validate & Simulate run yet"
          detail="Generate a USD stage, then click 'Validate & Simulate' above to run a real headless Isaac Sim render + PhysX collision check (scenes/standalone_render_and_validate.py)."
        />
      </div>
    );
  }

  if (status === 'queued' || status === 'running') {
    const elapsedMs = job?.startedAt ? Date.now() - job.startedAt : 0;
    return (
      <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div className="ph-card" style={{ padding: '28px', maxWidth: '480px', textAlign: 'center' }}>
          <Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-orange)', marginBottom: '14px' }} />
          <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', color: 'var(--text-main)', marginBottom: '8px' }}>
            {status === 'queued' ? 'Validation job queued...' : 'Running real Isaac Sim validation...'}
          </h3>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)', lineHeight: '1.6', marginBottom: '14px' }}>
            This is a real headless Isaac Sim render (RTX) + PhysX collision check — it can
            legitimately take several minutes, especially on a cold shader cache. This is
            normal, not stuck.
          </p>
          <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', marginBottom: '16px' }}>
            <span className="ph-badge ph-badge-grey">Elapsed: {formatElapsed(elapsedMs)}</span>
            {job?.currentFrame != null && (
              <span className="ph-badge ph-badge-grey">Captured frame {job.currentFrame}</span>
            )}
          </div>
          {onCheckStatusNow && (
            <button className="ph-btn ph-btn-sm" onClick={onCheckStatusNow}>
              <RefreshCw size={13} />
              Check again
            </button>
          )}
        </div>
      </div>
    );
  }

  if (status === 'failed') {
    return (
      <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div className="ph-card" style={{ padding: '28px', maxWidth: '520px', textAlign: 'center' }}>
          <ShieldX size={36} style={{ color: '#F87171', marginBottom: '14px' }} />
          <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', color: '#F87171', marginBottom: '8px' }}>
            Validation failed
          </h3>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '11.5px', color: 'var(--text-muted)', lineHeight: '1.6', whiteSpace: 'pre-wrap', textAlign: 'left', maxHeight: '240px', overflowY: 'auto' }}>
            {error || 'Unknown error. Check backend logs for details.'}
          </p>
          {onCheckStatusNow && (
            <button className="ph-btn ph-btn-sm" style={{ marginTop: '14px' }} onClick={onCheckStatusNow}>
              <RefreshCw size={13} />
              Check again
            </button>
          )}
        </div>
      </div>
    );
  }

  if (!result) {
    return null;
  }

  const renderFiles = result.render_files || [];
  const videoFile = result.video_file;
  const collisionFlags = result.collision_flags || [];
  const validationResult = result.validation_result || {};
  const hasIssues = collisionFlags.length > 0;

  return (
    <div style={{ width: '100%', height: '100%', overflowY: 'auto', padding: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
        <span className={`ph-badge ${validationResult.status === 'OK' ? 'ph-badge-green' : 'ph-badge-yellow'}`}>
          {validationResult.status === 'OK' ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
          Validation: {validationResult.status || 'unknown'}
        </span>
        <span className="ph-badge ph-badge-grey">{result.frame_count || 0} frame(s)</span>
        {result.s3_bucket && (
          <span className="ph-badge ph-badge-grey" style={{ fontFamily: 'var(--font-mono)' }}>
            s3://{result.s3_bucket}/{result.s3_prefix}
          </span>
        )}
      </div>

      {hasIssues && onGenerateFixReport && !fixReport && (
        <div className="ph-card" style={{
          padding: '12px 16px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          border: '1px solid var(--border-accent)'
        }}>
          <span style={{ fontSize: '12.5px', color: 'var(--text-main)' }}>
            {collisionFlags.length} collision flag(s) detected from the real PhysX validation.
          </span>
          <button
            className="ph-btn ph-btn-sm ph-btn-yellow"
            onClick={onGenerateFixReport}
            disabled={isGeneratingReport}
          >
            {isGeneratingReport ? 'Analyzing...' : 'Generate Fix Report'}
          </button>
        </div>
      )}

      {fixReport && (
        <FixReportCard
          report={fixReport}
          onApply={onApplyFixReport}
          isApplying={isApplyingFix}
          onDismiss={onDismissFixReport}
          applyLabel="Apply & Re-validate"
        />
      )}

      {videoFile && (
        <div className="ph-card" style={{ overflow: 'hidden', padding: 0, marginBottom: '16px' }}>
          <video src={videoFile} controls style={{ width: '100%', display: 'block', backgroundColor: '#000' }} />
          <div style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid var(--border-subtle)' }}>
            Stitched from {result.frame_count || 0} real Isaac Sim RTX frame(s)
          </div>
        </div>
      )}

      {renderFiles.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '14px', marginBottom: '20px' }}>
          {renderFiles.map((src, i) => (
            <div key={i} className="ph-card" style={{ overflow: 'hidden', padding: 0 }}>
              <img
                src={src}
                alt={`frame ${i}`}
                style={{ width: '100%', display: 'block', aspectRatio: '16 / 9', objectFit: 'cover', backgroundColor: '#0F172A' }}
              />
            </div>
          ))}
        </div>
      )}

      <FlagPanel
        title={`Collision Flags (${collisionFlags.length})`}
        empty="No frustum-off-set or camera-body collisions flagged."
        items={collisionFlags.map((f) => ({
          ok: false,
          label: f.type,
          detail: f.type === 'camera_body_collision'
            ? `frame ${f.frame} — colliding with ${(f.colliding_with || []).join(', ')}`
            : `frame ${f.frame}, corner ${f.corner}${f.prim ? ` — hit ${f.prim}` : ' — escaped the frustum'}`,
        }))}
      />

      <details style={{ marginTop: '16px' }}>
        <summary style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', cursor: 'pointer' }}>
          Raw validation_result.json
        </summary>
        <pre style={{
          fontSize: '10.5px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-muted)',
          backgroundColor: '#0F172A',
          padding: '10px',
          borderRadius: '6px',
          overflowX: 'auto',
          marginTop: '8px',
        }}>
          {JSON.stringify(validationResult, null, 2)}
        </pre>
      </details>
    </div>
  );
}
