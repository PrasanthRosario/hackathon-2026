import React, { useState } from 'react';
import ThreeCanvas from './ThreeCanvas';
import OmniverseStreamView from './OmniverseStreamView';
import { Box, Radio, Layers } from 'lucide-react';

export default function RenderView({ sceneConfig, usdStatus }) {
  const [renderMode, setRenderMode] = useState('threejs');

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
        </div>

        {/* Viewport Meta Details */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="ph-badge ph-badge-grey">
            <Layers size={11} />
            Walls: {sceneConfig?.walls?.length || 0} | Shots: {sceneConfig?.shots?.length || 0}
          </span>
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
      </div>
    </div>
  );
}
