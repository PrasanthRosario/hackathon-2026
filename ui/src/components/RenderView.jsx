import React from 'react';
import ValidateSimulateResultView from './ValidateSimulateResultView';
import { Loader2, ShieldCheck, Download, FileBox } from 'lucide-react';

export default function RenderView({
  usdStatus,
  onDownloadUsd,
  onGenerateFixReportFromValidateSimulate,
  isGeneratingReport,
  fixReport,
  fixReportSource,
  onApplyFixReport,
  isApplyingFix,
  onDismissFixReport,
  onValidateAndSimulate,
  validateStatus,
  validateJob,
  validateResult,
  validateError,
  onCheckValidateStatusNow,
  usdCameras,
  selectedCamera,
  onSelectCamera,
  isLoadingCameras,
  cameraListError,
}) {
  const isValidating = validateStatus === 'queued' || validateStatus === 'running';

  const hasUsd = !!usdStatus?.usd_path;
  const usdFilename = usdStatus?.usd_path?.split('/').pop();
  const noCamerasInUsd = hasUsd && !isLoadingCameras && (usdCameras || []).length === 0;
  const validateDisabledReason = !hasUsd
    ? 'Generate a USD stage first'
    : isLoadingCameras
      ? 'Checking which cameras this USD file actually has...'
      : noCamerasInUsd
        ? 'This USD file has no Camera prim -- nothing to render/validate through'
        : 'Run a real headless Isaac Sim render + PhysX validation through the selected camera';

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
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginRight: '6px' }}>
            VIEWPORT:
          </span>
          <span className="ph-btn ph-btn-sm ph-btn-primary" style={{ pointerEvents: 'none' }}>
            <ShieldCheck size={13} />
            Validate & Simulate Result
          </span>
        </div>

        {/* Viewport Meta Details */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {hasUsd && (
            <span className="ph-badge ph-badge-grey" title={usdStatus?.usd_path}>
              <FileBox size={11} />
              {usdFilename} · {(usdCameras || []).length} camera{(usdCameras || []).length === 1 ? '' : 's'}
            </span>
          )}

          <button
            className="ph-btn ph-btn-sm"
            onClick={onDownloadUsd}
            disabled={!usdStatus?.usd_content}
            title={!usdStatus?.usd_content ? 'Generate a USD stage first' : 'Download the generated .usda file'}
          >
            <Download size={13} />
            Download USD
          </button>

          {hasUsd && (
            <span title={cameraListError ? `Failed to list cameras: ${cameraListError}` : undefined}>
              <select
                className="ph-btn ph-btn-sm"
                value={selectedCamera || ''}
                onChange={(e) => onSelectCamera(e.target.value)}
                disabled={isLoadingCameras || noCamerasInUsd || (usdCameras || []).length === 0}
                style={{ paddingRight: '8px' }}
              >
                {isLoadingCameras && <option value="">Checking cameras...</option>}
                {!isLoadingCameras && noCamerasInUsd && <option value="">No camera in USD</option>}
                {!isLoadingCameras && (usdCameras || []).map((cam) => (
                  <option key={cam.path} value={cam.path}>{cam.name}</option>
                ))}
              </select>
            </span>
          )}

          <button
            className="ph-btn ph-btn-sm ph-btn-yellow"
            onClick={onValidateAndSimulate}
            disabled={!hasUsd || isValidating || isLoadingCameras || noCamerasInUsd}
            title={validateDisabledReason}
          >
            {isValidating ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />}
            {isValidating ? 'Validating...' : 'Validate & Simulate'}
          </button>
        </div>
      </div>

      {/* Main Render Area */}
      <div style={{ flex: 1, position: 'relative', width: '100%', height: '100%' }}>
        <ValidateSimulateResultView
          status={validateStatus}
          job={validateJob}
          result={validateResult}
          error={validateError}
          onCheckStatusNow={onCheckValidateStatusNow}
          onGenerateFixReport={onGenerateFixReportFromValidateSimulate}
          isGeneratingReport={isGeneratingReport}
          fixReport={fixReportSource === 'validate_simulate' ? fixReport : null}
          onApplyFixReport={onApplyFixReport}
          isApplyingFix={isApplyingFix}
          onDismissFixReport={onDismissFixReport}
        />
      </div>
    </div>
  );
}
