import React, { useState } from 'react';
import { Loader2, AlertTriangle, ImageOff, CheckCircle2, XCircle, Wrench, FolderInput, Sparkles } from 'lucide-react';

export default function KitRenderResultView({
  status,
  result,
  error,
  onGenerateFixReport,
  isGeneratingReport,
  fixReport,
  onApplyFixReport,
  isApplyingFix,
  onDismissFixReport,
  onIngestKitOutput,
  isIngesting,
}) {
  if (status === 'idle') {
    return (
      <div style={{ width: '100%', height: '100%', overflowY: 'auto', padding: '20px' }}>
        <EmptyState
          icon={<ImageOff size={36} style={{ color: 'var(--text-muted)' }} />}
          title="No Kit render yet"
          detail="Generate a USD stage, then click 'Render in Kit' above to invoke kit_render_worker.py and see real render/physics/coverage output here."
        />
        <IngestForm onIngestKitOutput={onIngestKitOutput} isIngesting={isIngesting} />
      </div>
    );
  }

  if (status === 'rendering') {
    return (
      <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <EmptyState
          icon={<Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-orange)' }} />}
          title="Rendering in Kit..."
          detail="Invoking kit_render_worker.py via subprocess. This runs RTX render, PhysX stability check, and frustum coverage check per camera."
        />
      </div>
    );
  }

  if (status === 'failed') {
    return (
      <div style={{ width: '100%', height: '100%', overflowY: 'auto', padding: '20px' }}>
        <EmptyState
          icon={<AlertTriangle size={36} style={{ color: '#F87171' }} />}
          title="Kit render failed"
          detail={error || 'Unknown error. Check backend logs / render.log for details.'}
          isError
        />
        <IngestForm onIngestKitOutput={onIngestKitOutput} isIngesting={isIngesting} />
      </div>
    );
  }

  if (!result) {
    return null;
  }

  const renderFiles = result.render_files || [];
  const videoFiles = result.video_files || [];
  const coverageFlags = result.coverage_flags || [];
  const physicsFlags = result.physics_flags || [];
  const collisionFlags = result.collision_flags || [];
  const unstableCount = physicsFlags.filter((f) => !f.stable).length;
  const hasIssues = coverageFlags.length > 0 || unstableCount > 0 || collisionFlags.length > 0;

  return (
    <div style={{ width: '100%', height: '100%', overflowY: 'auto', padding: '20px' }}>
      {result.source === 'kit_ingested' && (
        <div className="ph-badge ph-badge-grey" style={{ marginBottom: '14px', display: 'inline-flex' }}>
          Loaded from real Kit capture: {result.source_dir}
        </div>
      )}

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
            {coverageFlags.length} coverage flag(s), {unstableCount} physics flag(s), {collisionFlags.length} collision flag(s) detected.
          </span>
          <button
            className="ph-btn ph-btn-sm ph-btn-yellow"
            onClick={onGenerateFixReport}
            disabled={isGeneratingReport}
          >
            {isGeneratingReport ? <Loader2 size={13} className="animate-spin" /> : <Wrench size={13} />}
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
        />
      )}

      {/* Video Playback */}
      {videoFiles.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '16px' }}>
          {videoFiles.map((src, i) => (
            <div key={i} className="ph-card" style={{ overflow: 'hidden', padding: 0 }}>
              <video src={src} controls style={{ width: '100%', display: 'block', backgroundColor: '#000' }} />
              <div style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid var(--border-subtle)' }}>
                {src.split('/').pop()}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Render Images Grid */}
      {renderFiles.length > 0 && (
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
      )}

      {/* Flags */}
      <div style={{ display: 'grid', gridTemplateColumns: collisionFlags.length > 0 ? '1fr 1fr 1fr' : '1fr 1fr', gap: '14px' }}>
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
        {collisionFlags.length > 0 && (
          <FlagPanel
            title={`Collision Flags (${collisionFlags.length})`}
            empty="No rig collisions flagged."
            items={collisionFlags.map((f) => ({
              ok: false,
              label: f.prim_id || f.target_id || 'unknown',
              detail: f.detail || JSON.stringify(f),
            }))}
          />
        )}
      </div>

      <IngestForm onIngestKitOutput={onIngestKitOutput} isIngesting={isIngesting} />
    </div>
  );
}

function FixReportCard({ report, onApply, isApplying, onDismiss }) {
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
          {isApplying ? 'Applying & Re-verifying...' : 'Apply & Re-render'}
        </button>
        <button className="ph-btn ph-btn-sm" onClick={onDismiss} disabled={isApplying}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

function IngestForm({ onIngestKitOutput, isIngesting }) {
  const [sourceDir, setSourceDir] = useState('');
  if (!onIngestKitOutput) return null;

  return (
    <div className="ph-card" style={{ padding: '14px', marginTop: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
        <FolderInput size={14} style={{ color: 'var(--text-muted)' }} />
        <h4 style={{ fontFamily: 'var(--font-heading)', fontSize: '12.5px', color: 'var(--text-main)' }}>
          Load Real Kit Output (EC2)
        </h4>
      </div>
      <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px', lineHeight: '1.5' }}>
        Point this at a folder on this machine holding a real Kit render/capture (PNG frames and/or an MP4) —
        e.g. output from running Kit's Movie Capture extension directly. It'll be copied into the render output
        and shown above like any other render.
      </p>
      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          type="text"
          value={sourceDir}
          onChange={(e) => setSourceDir(e.target.value)}
          placeholder="/home/ubuntu/kit_captures/run1"
          style={{
            flex: 1,
            padding: '8px 12px',
            backgroundColor: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '6px',
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            color: 'var(--text-main)',
            outline: 'none'
          }}
        />
        <button
          className="ph-btn ph-btn-sm"
          onClick={() => onIngestKitOutput(sourceDir.trim())}
          disabled={!sourceDir.trim() || isIngesting}
        >
          {isIngesting ? <Loader2 size={13} className="animate-spin" /> : <FolderInput size={13} />}
          {isIngesting ? 'Loading...' : 'Ingest'}
        </button>
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
