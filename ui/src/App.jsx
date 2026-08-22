import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import LeftPanel from './components/LeftPanel';
import RenderView from './components/RenderView';
import {
  checkCoverage,
  checkPhysics,
  downloadUsdFromPrompt,
  generateUsd,
  getValidateSimulateStatus,
  listUsdCameras,
  sendChatTurn,
  startValidateSimulate
} from './api/offsetAgent';

const VALIDATE_POLL_INTERVAL_MS = 5000;
const VALIDATE_POLL_GIVE_UP_MS = 20 * 60 * 1000; // 20 min -- above the backend's own ~17 min budget (900s render + 120s stitch + upload)

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Welcome to Off Frame! I am your pre-visualization set validation assistant for NVIDIA Omniverse. Describe your film set (e.g., "2 walls forming a corner, 4m wide, with a floor and 3m ceiling"), and I will help you refine and validate it.',
      model_used: 'offset-agent'
    }
  ]);

  // Default scene state starts clean (no pre-extracted confirmation card)
  const [sceneConfig, setSceneConfig] = useState(null);
  const [currentScene, setCurrentScene] = useState(null);
  const [currentModel, setCurrentModel] = useState('offset-agent');
  const [isLoading, setIsLoading] = useState(false);
  const [readyForConfirmation, setReadyForConfirmation] = useState(false);
  const [readableSummary, setReadableSummary] = useState(null);
  const [usdStatus, setUsdStatus] = useState(null);
  const [isGeneratingUSD, setIsGeneratingUSD] = useState(false);
  const [isDownloadingPromptUSD, setIsDownloadingPromptUSD] = useState(false);
  const [checkResults, setCheckResults] = useState(null);
  const [fixReport, setFixReport] = useState(null); // { summary, fixes, updated_scene_config, model_used } | null
  const [fixReportSource, setFixReportSource] = useState(null); // 'validate_simulate' | null
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [isApplyingFix, setIsApplyingFix] = useState(false);
  const [chatMode, setChatMode] = useState('preview');

  // Cameras actually present in the current USD file (parsed server-side via
  // pxr, not assumed from the in-memory scene -- some USDs have no camera at
  // all, e.g. externally-authored ones or a build path that skipped adding one).
  const [usdCameras, setUsdCameras] = useState([]); // [{path, name}]
  const [selectedCamera, setSelectedCamera] = useState(null);
  const [isLoadingCameras, setIsLoadingCameras] = useState(false);
  const [cameraListError, setCameraListError] = useState(null);

  // Validate & Simulate (async /validate-usd job) state
  const [validateStatus, setValidateStatus] = useState('idle'); // idle | queued | running | done | failed
  const [validateJob, setValidateJob] = useState(null); // { sceneId, startedAt, currentFrame } | null
  const [validateResult, setValidateResult] = useState(null); // the "done" result payload | null
  const [validateError, setValidateError] = useState(null);
  const pollIntervalRef = useRef(null);

  const downloadBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const filenameFromPrompt = (prompt) => {
    const slug = prompt
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 48);
    return `${slug || 'agent_generated'}.usda`;
  };

  // Send conversational turn to FastAPI backend (/api/chat)
  const handleSendMessage = async (text) => {
    const userMsg = { role: 'user', content: text };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setIsLoading(true);

    try {
      if (chatMode === 'usd-file') {
        const outputFilename = filenameFromPrompt(text);
        setIsDownloadingPromptUSD(true);
        const download = await downloadUsdFromPrompt({
          prompt: text,
          messages,
          outputFilename
        });
        downloadBlob(download.blob, outputFilename);

        // Point usdStatus at the file that was just downloaded (the
        // usd_script_agent-produced one), not the /generate-usd scene
        // pipeline's generated_set.usda -- this is what Validate & Simulate
        // and the camera picker read (usdStatus?.usd_path), so this makes
        // them operate on exactly the file the user just downloaded.
        if (download.path) {
          const usdContent = await download.blob.text();
          setUsdStatus({
            status: 'SUCCESS',
            usd_path: download.path,
            usd_content: usdContent,
            prim_count: null,
            message: `Generated via ${download.source}`,
          });
        }

        const previewData = await sendChatTurn({
          messages: updatedMessages,
          currentConfig: sceneConfig,
          currentScene
        });

        setCurrentModel(download.source === 'llm-deepagent' ? 'usd-script-agent' : 'deterministic-fallback');
        setReadyForConfirmation(previewData.ready_for_confirmation);
        if (previewData.scene_config) {
          setSceneConfig(previewData.scene_config);
        }
        if (previewData.scene) {
          setCurrentScene(previewData.scene);
        }
        if (previewData.readable_summary) {
          setReadableSummary(previewData.readable_summary);
        }

        setMessages([
          ...updatedMessages,
          {
            role: 'assistant',
            content: `USD file generated via ${download.source} and downloaded as \`${outputFilename}\` (${download.sizeBytes.toLocaleString()} bytes). I also updated the Three.js preview from the same prompt.`,
            model_used: download.source === 'llm-deepagent' ? 'usd-script-agent' : 'deterministic-fallback'
          }
        ]);
        return;
      }

      const data = await sendChatTurn({
        messages: updatedMessages,
        currentConfig: sceneConfig,
        currentScene
      });

      setMessages([
        ...updatedMessages,
        {
          role: 'assistant',
          content: data.message,
          model_used: data.model_used
        }
      ]);

      setCurrentModel(data.model_used);
      setReadyForConfirmation(data.ready_for_confirmation);

      if (data.scene_config) {
        setSceneConfig(data.scene_config);
      }
      if (data.scene) {
        setCurrentScene(data.scene);
      }
      if (data.readable_summary) {
        setReadableSummary(data.readable_summary);
      }
    } catch (err) {
      console.error('Chat error:', err);
      setMessages([
        ...updatedMessages,
        {
          role: 'assistant',
          content: `Sorry, I could not complete that chat request. ${err.message}`,
          model_used: 'error'
        }
      ]);
    } finally {
      setIsDownloadingPromptUSD(false);
      setIsLoading(false);
    }
  };

  // POST /api/generate-usd
  const handleConfirmGenerateUSD = async () => {
    if (!sceneConfig && !currentScene) return;
    setIsGeneratingUSD(true);

    try {
      const data = await generateUsd({
        sceneConfig: sceneConfig || { walls: [], floor: { width: 8, depth: 6 }, shots: [] },
        currentScene,
        outputFilename: 'generated_set.usda'
      });
      setUsdStatus(data);

      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `✅ **USD Stage Generated Successfully!**\nStage file saved to \`${data.usd_path}\` with ${data.prim_count} prims. Live 3D preview updated.`,
          model_used: 'anthropic/claude-sonnet-4-6'
        }
      ]);
    } catch (err) {
      console.error('Generate USD error:', err);
      alert('Failed to generate USD file.');
    } finally {
      setIsGeneratingUSD(false);
    }
  };

  const handleDownloadPromptUSD = async (prompt) => {
    if (!prompt.trim() || isDownloadingPromptUSD) return;
    setIsDownloadingPromptUSD(true);

    try {
      const outputFilename = filenameFromPrompt(prompt);
      const download = await downloadUsdFromPrompt({
        prompt,
        messages,
        outputFilename
      });
      downloadBlob(download.blob, outputFilename);

      // Same as the usd-file chat-mode branch above: make Validate & Simulate
      // and the camera picker operate on this file instead of generated_set.usda.
      if (download.path) {
        const usdContent = await download.blob.text();
        setUsdStatus({
          status: 'SUCCESS',
          usd_path: download.path,
          usd_content: usdContent,
          prim_count: null,
          message: `Generated via ${download.source}`,
        });
      }

      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `USD file generated via ${download.source} and downloaded as \`${outputFilename}\` (${download.sizeBytes.toLocaleString()} bytes).`,
          model_used: download.source === 'llm-deepagent' ? 'usd-script-agent' : 'deterministic-fallback'
        }
      ]);
    } catch (err) {
      console.error('Download USD error:', err);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `Sorry, I could not generate the USD download. ${err.message}`,
          model_used: 'error'
        }
      ]);
    } finally {
      setIsDownloadingPromptUSD(false);
    }
  };

  // Downloads the USD stage that /api/generate-usd already produced (usd_content
  // is already in memory from that response) -- distinct from the prompt-driven
  // /chat-usd-file download flow, which re-generates from a prompt via a fresh
  // backend call. Purely client-side, no network request.
  const handleDownloadGeneratedUsd = () => {
    if (!usdStatus?.usd_content) return;
    const blob = new Blob([usdStatus.usd_content], { type: 'model/vnd.usda' });
    const filename = usdStatus.usd_path?.split('/').pop() || 'generated_set.usda';
    downloadBlob(blob, filename);
  };

  // Whenever the current USD stage changes, ask the backend which cameras
  // ACTUALLY exist in that file (POST /list-usd-cameras, plain pxr parsing --
  // not a render, not Isaac Sim). Deliberately not derived from currentScene's
  // in-memory cameras list: /validate-usd takes an arbitrary usda_path, which
  // might not match 1:1 with the current chat scene, and some USD files have
  // no camera at all, so the picker must reflect the real file.
  useEffect(() => {
    const usdaPath = usdStatus?.usd_path;
    if (!usdaPath) {
      setUsdCameras([]);
      setSelectedCamera(null);
      setCameraListError(null);
      return;
    }

    let cancelled = false;
    setIsLoadingCameras(true);
    setCameraListError(null);

    listUsdCameras(usdaPath)
      .then((data) => {
        if (cancelled) return;
        const cameras = data.cameras || [];
        setUsdCameras(cameras);
        // Prefer a camera literally named/pathed "MainCamera" if present,
        // otherwise fall back to whichever camera is listed first. If the
        // USD has none at all, selectedCamera stays null and the UI must
        // not let Validate & Simulate silently default to a path that isn't there.
        const main = cameras.find((c) => c.name === 'MainCamera' || c.path.endsWith('/MainCamera'));
        setSelectedCamera(main?.path || cameras[0]?.path || null);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('List USD cameras error:', err);
        setUsdCameras([]);
        setSelectedCamera(null);
        setCameraListError(err.message);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingCameras(false);
      });

    return () => { cancelled = true; };
  }, [usdStatus?.usd_path]);

  // POST /api/validate-usd -> kicks off a REAL headless Isaac Sim render+validate
  // job (backend runs it in a background thread and returns immediately). We then
  // poll GET /api/validate-usd/{scene_id}/status until it's done or failed --
  // this can legitimately take minutes, so there's no single blocking await here.
  // Accepts an optional usdaPathOverride so the fix-and-reverify loop below can
  // validate a just-regenerated stage without waiting on a state update.
  const handleValidateAndSimulate = async (usdaPathOverride, beforeCollisionCount) => {
    const usdaPath = usdaPathOverride || usdStatus?.usd_path;
    if (!usdaPath) return;

    setValidateStatus('queued');
    setValidateError(null);
    setValidateResult(null);

    const sceneId = `validate_${Date.now()}`;

    try {
      await startValidateSimulate({
        usdaPath,
        sceneId,
        ...(selectedCamera ? { camera: selectedCamera } : {}),
      });
      setValidateJob({ sceneId, startedAt: Date.now(), currentFrame: null, beforeCollisionCount });
    } catch (err) {
      console.error('Validate & Simulate error:', err);
      setValidateStatus('failed');
      setValidateError(err.message);
    }
  };

  // Polling loop for the active validate job -- the first client-side polling
  // loop in this app (GET /render/{scene_id}/status exists server-side too, but
  // nothing calls it; "Render in Kit" is a single blocking fetch instead).
  useEffect(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (!validateJob?.sceneId) return undefined;

    const { sceneId, startedAt } = validateJob;

    const tick = async () => {
      if (Date.now() - startedAt > VALIDATE_POLL_GIVE_UP_MS) {
        // Stop auto-polling past a generous ceiling, but don't fabricate a
        // failure -- the job may genuinely still be running; the result view
        // offers a manual "Check again" button that re-invokes this same tick.
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
        return;
      }

      try {
        const status = await getValidateSimulateStatus(sceneId);

        if (status.status === 'done') {
          setValidateStatus('done');
          setValidateResult(status.result);
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;

          const vr = status.result?.validation_result || {};
          const collisionCount = (status.result?.collision_flags || []).length;
          const before = validateJob.beforeCollisionCount;
          const diffLine = typeof before === 'number'
            ? ` Collision flags: ${before} → ${collisionCount}${collisionCount < before ? ' ✅ improved' : collisionCount === before ? ' ⚠️ unchanged' : ' 🔻 worse'}.`
            : '';
          setMessages(prev => [
            ...prev,
            {
              role: 'assistant',
              content: `🧪 **Validate & Simulate complete.**\n${status.result?.frame_count || 0} frame(s) rendered via real Isaac Sim RTX + PhysX. Validation status: **${vr.status || 'unknown'}**, ${collisionCount} collision flag(s).${diffLine}`,
              model_used: 'isaac_sim_validator'
            }
          ]);
        } else if (status.status === 'failed') {
          setValidateStatus('failed');
          setValidateError(status.error || 'Validation job failed.');
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        } else if (status.status === 'not_found') {
          setValidateStatus('failed');
          setValidateError('Validation job not found on the backend.');
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        } else {
          setValidateStatus(status.status); // 'queued' | 'running'
          setValidateJob(prev => prev && prev.sceneId === sceneId
            ? { ...prev, currentFrame: status.current_frame ?? prev.currentFrame }
            : prev);
        }
      } catch (err) {
        console.error('Validate status poll error:', err);
        // Transient network hiccup -- keep polling rather than failing the job outright.
      }
    };

    tick(); // immediate check, don't wait a full interval for the first update
    pollIntervalRef.current = setInterval(tick, VALIDATE_POLL_INTERVAL_MS);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validateJob?.sceneId]);

  const handleCheckValidateStatusNow = () => {
    if (!validateJob?.sceneId) return;
    // Re-arm the effect by touching validateJob's identity via a no-op setState
    // isn't necessary here -- the interval is already running (or the give-up
    // ceiling was hit). For a manual re-check, just run one immediate poll.
    getValidateSimulateStatus(validateJob.sceneId)
      .then((status) => {
        if (status.status === 'done') {
          setValidateStatus('done');
          setValidateResult(status.result);
        } else if (status.status === 'failed' || status.status === 'not_found') {
          setValidateStatus('failed');
          setValidateError(status.error || 'Validation job failed or was not found.');
        } else {
          setValidateStatus(status.status);
          setValidateJob(prev => prev ? { ...prev, currentFrame: status.current_frame ?? prev.currentFrame } : prev);
        }
      })
      .catch((err) => console.error('Manual validate status check error:', err));
  };

  // POST /api/propose-fix -> Sonnet fix-proposer agent (fix_agent.py) reasons over
  // evidence (collision flags from a real Validate & Simulate run) and proposes
  // fixes from a fixed set of types, plus a plain-language summary. This ONLY
  // generates the report - it does not touch scene_config or trigger a
  // re-validate. The director reviews it and decides whether to apply it
  // (handleApplyFixReport below).
  const handleGenerateFixReport = async (evidence, source = 'validate_simulate') => {
    if (!sceneConfig || !evidence) return;
    setIsGeneratingReport(true);
    setFixReport(null);
    setFixReportSource(source);

    try {
      const fixRes = await fetch('/api/propose-fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scene_config: sceneConfig,
          coverage_flags: evidence.coverage_flags || [],
          physics_flags: evidence.physics_flags || [],
          collision_flags: evidence.collision_flags || [],
        })
      });

      if (!fixRes.ok) {
        const errBody = await fixRes.json().catch(() => ({}));
        throw new Error(errBody.detail || `Fix proposal failed with status ${fixRes.status}`);
      }

      const fixData = await fixRes.json();
      setFixReport(fixData);
    } catch (err) {
      console.error('Generate fix report error:', err);
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `Fix report failed: ${err.message}`, model_used: 'error' }
      ]);
    } finally {
      setIsGeneratingReport(false);
    }
  };

  const handleGenerateFixReportFromValidateSimulate = () => {
    if (!validateResult) return;
    handleGenerateFixReport({
      coverage_flags: [],
      physics_flags: [],
      collision_flags: validateResult.collision_flags || [],
    }, 'validate_simulate');
  };

  // Applies a previously-generated fix report: mutates scene_config, regenerates
  // USD, then re-runs Validate & Simulate to verify. Only runs when the
  // director explicitly clicks Apply.
  const handleApplyFixReport = async () => {
    if (!fixReport) return;
    setIsApplyingFix(true);

    const flagsBefore = {
      collisions: (validateResult?.collision_flags || []).length,
    };
    const fixes = fixReport.fixes || [];

    try {
      setSceneConfig(fixReport.updated_scene_config);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `🔧 **Applying ${fixes.length} fix(es):**\n${fixes.map(f => `- **${f.fix_type}** on \`${f.target_id}\`: ${f.rationale}`).join('\n')}\n\nRegenerating USD and re-validating to verify...`,
          model_used: fixReport.model_used,
        }
      ]);

      const usdRes = await fetch('/api/generate-usd', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scene_config: fixReport.updated_scene_config,
          output_filename: 'generated_set.usda'
        })
      });
      const usdData = await usdRes.json();
      setUsdStatus(usdData);

      // Kicks off a new async validate job; the before/after comparison
      // message is posted from the polling loop's 'done' handler once this
      // new run actually completes, since it no longer resolves synchronously.
      await handleValidateAndSimulate(usdData.usd_path, flagsBefore.collisions);

      setFixReport(null);
      setFixReportSource(null);
    } catch (err) {
      console.error('Apply fix error:', err);
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `Applying the fix failed: ${err.message}`, model_used: 'error' }
      ]);
    } finally {
      setIsApplyingFix(false);
    }
  };

  const handleDismissFixReport = () => {
    setFixReport(null);
    setFixReportSource(null);
  };

  // Verification Suite Callbacks
  const handleCheckCoverage = async () => {
    if (!sceneConfig) return;
    try {
      const data = await checkCoverage(sceneConfig);
      setCheckResults(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleCheckPhysics = async () => {
    if (!sceneConfig) return;
    try {
      const data = await checkPhysics(sceneConfig);
      setCheckResults(data);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="app-container">
      <Header
        currentModel={currentModel}
        usdStatus={usdStatus}
      />

      <main className="split-screen">
        <LeftPanel
          messages={messages}
          onSendMessage={handleSendMessage}
          chatMode={chatMode}
          onChatModeChange={setChatMode}
          isLoading={isLoading}
          sceneConfig={sceneConfig}
          readableSummary={readableSummary}
          readyForConfirmation={readyForConfirmation}
          onConfirmGenerateUSD={handleConfirmGenerateUSD}
          isGeneratingUSD={isGeneratingUSD}
          isDownloadingPromptUSD={isDownloadingPromptUSD}
          usdStatus={usdStatus}
          onDownloadPromptUSD={handleDownloadPromptUSD}
          onCheckCoverage={handleCheckCoverage}
          onCheckPhysics={handleCheckPhysics}
          checkResults={checkResults}
        />

        <RenderView
          sceneConfig={sceneConfig}
          sceneSpec={currentScene}
          usdStatus={usdStatus}
          onDownloadUsd={handleDownloadGeneratedUsd}
          onGenerateFixReportFromValidateSimulate={handleGenerateFixReportFromValidateSimulate}
          isGeneratingReport={isGeneratingReport}
          fixReport={fixReport}
          fixReportSource={fixReportSource}
          onApplyFixReport={handleApplyFixReport}
          isApplyingFix={isApplyingFix}
          onDismissFixReport={handleDismissFixReport}
          onValidateAndSimulate={() => handleValidateAndSimulate()}
          validateStatus={validateStatus}
          validateJob={validateJob}
          validateResult={validateResult}
          validateError={validateError}
          onCheckValidateStatusNow={handleCheckValidateStatusNow}
          usdCameras={usdCameras}
          selectedCamera={selectedCamera}
          onSelectCamera={setSelectedCamera}
          isLoadingCameras={isLoadingCameras}
          cameraListError={cameraListError}
        />
      </main>
    </div>
  );
}
