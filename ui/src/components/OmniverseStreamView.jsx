import React, { useState } from 'react';
import { Video, Radio, Settings, RefreshCw, Cpu, Activity, Play } from 'lucide-react';

/**
 * OmniverseStreamView.jsx
 * 
 * SWAPPABLE SEAM COMPONENT FOR OMNIVERSE KIT BACKEND
 * 
 * This component acts as the explicit seam where the Three.js viewport
 * can be swapped for an embedded WebRTC stream or video feed from a
 * separately-running NVIDIA Omniverse Kit application instance.
 * 
 * TODO [Omniverse Team]: Replace the simulated video feed container below
 * with your WebRTC video stream client (e.g. NVIDIA Omniverse WebRTC App Streamer / AppStreamer SDK).
 */
export default function OmniverseStreamView({ usdPath }) {
  const [streamStatus, setStreamStatus] = useState('CONNECTED');
  const [fps, setFps] = useState(60);
  const [latency, setLatency] = useState('18ms');

  return (
    <div style={{
      width: '100%',
      height: '100%',
      backgroundColor: '#0F172A',
      color: '#F8FAFC',
      display: 'flex',
      flexDirection: 'column',
      position: 'relative'
    }}>
      {/* Stream Top Status Header */}
      <div style={{
        padding: '12px 16px',
        backgroundColor: '#1E293B',
        borderBottom: '2px solid #334155',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontFamily: 'var(--font-mono)',
        fontSize: '12px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div className="ph-badge ph-badge-green" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Radio size={12} className="animate-pulse" />
            <span>OMNIVERSE KIT WebRTC STREAM</span>
          </div>

          <span style={{ color: '#94A3B8' }}>
            Stage: {usdPath || 'scenes/generated_set.usda'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#10B981' }}>
            <Activity size={12} /> {fps} FPS
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#38BDF8' }}>
            <Cpu size={12} /> Latency: {latency}
          </span>
          <button 
            className="ph-btn ph-btn-sm" 
            style={{ backgroundColor: '#334155', color: '#FFF', borderColor: '#475569' }}
            onClick={() => setStreamStatus(streamStatus === 'CONNECTED' ? 'RECONNECTING' : 'CONNECTED')}
          >
            <RefreshCw size={12} /> Reconnect
          </button>
        </div>
      </div>

      {/* Main Stream Viewport (Simulated RTX Real-time Stream View) */}
      <div style={{
        flex: 1,
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(circle at center, #1E293B 0%, #0F172A 100%)',
        overflow: 'hidden'
      }}>
        {/* Placeholder Simulated RTX Render Frame */}
        <div style={{
          position: 'absolute',
          inset: 0,
          opacity: 0.15,
          backgroundImage: 'radial-gradient(#38BDF8 1px, transparent 1px)',
          backgroundSize: '24px 24px'
        }} />

        <div style={{
          textAlign: 'center',
          maxWidth: '480px',
          padding: '24px',
          zIndex: 2,
          backgroundColor: 'rgba(30, 41, 59, 0.85)',
          borderRadius: '12px',
          border: '2px solid #334155',
          backdropFilter: 'blur(8px)',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
        }}>
          <div style={{
            width: '64px',
            height: '64px',
            margin: '0 auto 16px auto',
            borderRadius: '50%',
            backgroundColor: 'rgba(16, 185, 129, 0.15)',
            border: '2px solid #10B981',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#10B981'
          }}>
            <Radio size={32} />
          </div>

          <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '18px', marginBottom: '8px', color: '#FFF' }}>
            NVIDIA Omniverse Kit WebRTC Seam
          </h3>

          <p style={{ fontFamily: 'var(--font-body)', fontSize: '13px', color: '94A3B8', marginBottom: '16px', lineHeight: '1.6' }}>
            This viewport component (<code>&lt;OmniverseStreamView /&gt;</code>) is configured as a swappable stub. When connected to a live Omniverse Kit instance, RTX path-traced rendering stream feeds directly into this WebRTC canvas.
          </p>

          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 12px',
            backgroundColor: '#0F172A',
            borderRadius: '6px',
            border: '1px solid #334155',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: '#7DD3FC'
          }}>
            <Settings size={12} />
            <span>ws://localhost:8899/omni/webrtc</span>
          </div>
        </div>
      </div>

      {/* Stream Bottom Telemetry Footer */}
      <div style={{
        padding: '8px 16px',
        backgroundColor: '#0F172A',
        borderTop: '1px solid #334155',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontFamily: 'var(--font-mono)',
        fontSize: '11px',
        color: '#64748B'
      }}>
        <span>RTX Mode: PathTracing (DLSS 3.5 On)</span>
        <span>Resolution: 1920x1080 @ 60.00 Hz</span>
        <span>WebRTC Codec: H.264 / NVENC</span>
      </div>
    </div>
  );
}
