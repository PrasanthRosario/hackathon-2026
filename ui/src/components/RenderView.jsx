import React, { useState } from 'react';
import ThreeCanvas from './ThreeCanvas';
import OmniverseStreamView from './OmniverseStreamView';
import KitRenderResultView from './KitRenderResultView';
import { Box, Radio, Layers, Zap, Loader2 } from 'lucide-react';

export default function RenderView({
  sceneConfig,
  usdStatus,
  onRenderInKit,
  kitRenderStatus,
  kitRenderResult,
  kitRenderError,
  onGenerateFixReport,
  isGeneratingReport,
  fixReport,
  onApplyFixReport,
  isApplyingFix,
  onDismissFixReport,
  onIngestKitOutput,
  isIngesting,
}) {
  const [renderMode, setRenderMode] = useState('threejs');
  const isRendering = kitRenderStatus === 'rendering';

  return (
    <div style={{
      width: '100%',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: 'var(--bg-dark)',
      position: 'relative',
      overflow: 'hidden'
    }}>
      {/* Top Seam Control Bar */}
      <div style={{
        height: '48px',
        backgroundColor: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-light)',
        padding: '0 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        zIndex: 5
      }}>
        {/* Render Mode Switcher Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginRight: '6px' }}>
            VIEWPORT SEAM:
          </span>

          <button
            className={`ph-btn ph-btn-sm ${renderMode === 'threejs' ? 'ph-btn-primary' : ''}`}
            onClick={() => setRenderMode('threejs')}
          >
            <Box size={13} />
            Three.js Live Preview
          </button>

          <button
            className={`ph-btn ph-btn-sm ${renderMode === 'omniverse_webrtc' ? 'ph-btn-yellow' : ''}`}
            onClick={() => setRenderMode('omniverse_webrtc')}
          >
            <Radio size={13} />
            Omniverse Kit Stream
          </button>

          <button
            className={`ph-btn ph-btn-sm ${renderMode === 'kit_result' ? 'ph-btn-primary' : ''}`}
            onClick={() => setRenderMode('kit_result')}
          >
            <Zap size={13} />
            Kit Render Result
          </button>
        </div>

        {/* Viewport Meta Details */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="ph-badge ph-badge-grey">
            <Layers size={11} />
            Walls: {sceneConfig?.walls?.length || 0} | Shots: {sceneConfig?.shots?.length || 0}
          </span>

          <button
            className="ph-btn ph-btn-sm ph-btn-yellow"
            onClick={() => {
              setRenderMode('kit_result');
              onRenderInKit();
            }}
            disabled={!usdStatus?.usd_content || isRendering}
            title={!usdStatus?.usd_content ? 'Generate a USD stage first' : 'Run kit_render_worker.py on the current stage'}
          >
            {isRendering ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
            {isRendering ? 'Rendering...' : 'Render in Kit'}
          </button>
        </div>
      </div>

      {/* Main Render Area */}
      <div style={{ flex: 1, position: 'relative', width: '100%', height: '100%' }}>
        {renderMode === 'threejs' && (
          <ThreeCanvas sceneConfig={sceneConfig} />
        )}

        {renderMode === 'omniverse_webrtc' && (
          <OmniverseStreamView usdPath={usdStatus?.usd_path} />
        )}

        {renderMode === 'kit_result' && (
          <KitRenderResultView
            status={kitRenderStatus || 'idle'}
            result={kitRenderResult}
            error={kitRenderError}
            onGenerateFixReport={onGenerateFixReport}
            isGeneratingReport={isGeneratingReport}
            fixReport={fixReport}
            onApplyFixReport={onApplyFixReport}
            isApplyingFix={isApplyingFix}
            onDismissFixReport={onDismissFixReport}
            onIngestKitOutput={onIngestKitOutput}
            isIngesting={isIngesting}
          />
        )}
      </div>
    </div>
  );
}
