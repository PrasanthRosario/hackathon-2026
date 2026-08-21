import React from 'react';
import { Film, Box, Cpu, Sparkles, CheckCircle2, ShieldAlert } from 'lucide-react';

function getRouteLabel(currentModel) {
  if (!currentModel) return 'haiku-latest';
  if (currentModel === 'usd-script-agent') return 'USD Agent';
  if (currentModel === 'deterministic-fallback') return 'Fallback';
  return currentModel.split('/')[1] || currentModel;
}

export default function Header({ currentModel, usdStatus, onLoadPreset }) {
  return (
    <header style={{
      height: '62px',
      backgroundColor: 'var(--bg-surface)',
      borderBottom: '1px solid var(--border-light)',
      padding: '0 24px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      zIndex: 10,
      backdropFilter: 'blur(12px)'
    }}>
      {/* Brand & Hackathon Title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        <div style={{
          background: 'linear-gradient(135deg, #F54E00 0%, #D94400 100%)',
          color: '#FFF',
          padding: '6px 12px',
          borderRadius: '8px',
          border: '1px solid rgba(255,255,255,0.2)',
          boxShadow: '0 4px 14px var(--accent-orange-glow)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontFamily: 'var(--font-heading)',
          fontWeight: 800,
          fontSize: '17px',
          letterSpacing: '0.5px'
        }}>
          <Film size={19} />
          OFFSET
        </div>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 700, fontSize: '15px', color: 'var(--text-main)' }}>
            Film Set Pre-Visualization & Validation
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
            NVIDIA Omniverse Hackathon
          </span>
        </div>
      </div>

      {/* Preset Action Buttons & Status Indicators */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Preset Loaders */}
        <div style={{ display: 'flex', gap: '8px', marginRight: '6px' }}>
          <button 
            className="ph-btn ph-btn-sm" 
            onClick={() => onLoadPreset('bedroom')}
            title="Load standard 3-wall bedroom set preset"
          >
            <Box size={13} style={{ color: 'var(--accent-orange)' }} />
            Bedroom (3-Wall)
          </button>

          <button 
            className="ph-btn ph-btn-sm" 
            onClick={() => onLoadPreset('corridor')}
            title="Load 4-wall corridor set preset"
          >
            <Box size={13} style={{ color: 'var(--accent-blue)' }} />
            Corridor (4-Wall)
          </button>
        </div>

        {/* Model Route Badge */}
        <div className="ph-badge ph-badge-orange" style={{ padding: '5px 12px' }}>
          <Cpu size={13} />
          <span>Route: {getRouteLabel(currentModel)}</span>
        </div>

        {/* USD Generation Status */}
        {usdStatus && (
          <div className={`ph-badge ${usdStatus.status === 'SUCCESS' ? 'ph-badge-green' : 'ph-badge-yellow'}`}>
            {usdStatus.status === 'SUCCESS' ? <CheckCircle2 size={12} /> : <ShieldAlert size={12} />}
            <span>USD: {usdStatus.status}</span>
          </div>
        )}

        <div className="ph-badge ph-badge-blue">
          <Sparkles size={12} />
          <span>Omniverse USD</span>
        </div>
      </div>
    </header>
  );
}
