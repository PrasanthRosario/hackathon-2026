import React, { useState } from 'react';
import Header from './components/Header';
import LeftPanel from './components/LeftPanel';
import RenderView from './components/RenderView';
import {
  checkCoverage,
  checkPhysics,
  downloadUsdFromPrompt,
  generateUsd,
  proposeFix,
  sendChatTurn
} from './api/offsetAgent';

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Welcome to Offset! I am your pre-visualization set validation assistant for NVIDIA Omniverse. Describe your film set (e.g., "2 walls forming a corner, 4m wide, with a floor and 3m ceiling"), and I will help you refine and validate it.',
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
  const [kitRenderStatus, setKitRenderStatus] = useState('idle'); // idle | rendering | done | failed
  const [kitRenderResult, setKitRenderResult] = useState(null);
  const [kitRenderError, setKitRenderError] = useState(null);
  const [fixReport, setFixReport] = useState(null); // { summary, fixes, updated_scene_config, model_used } | null
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [isApplyingFix, setIsApplyingFix] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [chatMode, setChatMode] = useState('preview');

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

  // POST /api/render -> invokes kit_render_worker.py via subprocess and returns
  // render paths + coverage_flags + physics_flags for the current USD stage.
  // Accepts an optional usdContentOverride so callers (like the fix-and-reverify
  // loop below) can render a just-regenerated stage without waiting on a state update.
  const handleRenderInKit = async (usdContentOverride) => {
    const usdContent = usdContentOverride || usdStatus?.usd_content;
    if (!usdContent) return null;
    setKitRenderStatus('rendering');
    setKitRenderError(null);

    const sceneId = `scene_${Date.now()}`;

    try {
      const response = await fetch('/api/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          usd_content: usdContent,
          scene_id: sceneId
        })
      });

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        throw new Error(errBody.detail || `Render failed with status ${response.status}`);
      }

      const data = await response.json();
      setKitRenderResult(data);
      setKitRenderStatus('done');

      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `🎬 **Kit Render Complete.**\n${(data.render_files || []).length} camera(s) rendered. ${(data.coverage_flags || []).length} coverage flag(s), ${(data.physics_flags || []).filter(f => !f.stable).length} physics instability flag(s).`,
          model_used: 'kit_render_worker'
        }
      ]);
      return data;
    } catch (err) {
      console.error('Kit render error:', err);
      setKitRenderError(err.message);
      setKitRenderStatus('failed');
      return null;
    }
  };

  // POST /api/propose-fix -> Sonnet fix-proposer agent (fix_agent.py) reasons over
  // the latest coverage/physics flags and proposes fixes from a fixed set of types,
  // plus a plain-language summary. This ONLY generates the report - it does not
  // touch scene_config or trigger a re-render. The director reviews it and decides
  // whether to apply it (handleApplyFixReport below).
  const handleGenerateFixReport = async () => {
    if (!sceneConfig || !kitRenderResult) return;
    setIsGeneratingReport(true);
    setFixReport(null);

    try {
      const fixRes = await fetch('/api/propose-fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scene_config: sceneConfig,
          coverage_flags: kitRenderResult.coverage_flags || [],
          physics_flags: kitRenderResult.physics_flags || [],
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

  // Applies a previously-generated fix report: mutates scene_config, regenerates
  // USD, re-renders in Kit, and reports whether the flags actually cleared.
  // Only runs when the director explicitly clicks "Apply & Re-render".
  const handleApplyFixReport = async () => {
    if (!fixReport) return;
    setIsApplyingFix(true);

    const flagsBefore = {
      coverage: (kitRenderResult?.coverage_flags || []).length,
      physics: (kitRenderResult?.physics_flags || []).filter(f => !f.stable).length,
    };
    const fixes = fixReport.fixes || [];

    try {
      setSceneConfig(fixReport.updated_scene_config);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `🔧 **Applying ${fixes.length} fix(es):**\n${fixes.map(f => `- **${f.fix_type}** on \`${f.target_id}\`: ${f.rationale}`).join('\n')}\n\nRegenerating USD and re-rendering to verify...`,
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

      const reverifyResult = await handleRenderInKit(usdData.usd_content);

      if (reverifyResult) {
        const flagsAfter = {
          coverage: (reverifyResult.coverage_flags || []).length,
          physics: (reverifyResult.physics_flags || []).filter(f => !f.stable).length,
        };
        const resolved = flagsAfter.coverage < flagsBefore.coverage || flagsAfter.physics < flagsBefore.physics;
        const unchanged = flagsAfter.coverage === flagsBefore.coverage && flagsAfter.physics === flagsBefore.physics;
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: `${resolved ? '✅' : unchanged ? '⚠️' : '🔻'} **Re-verification result:** coverage flags ${flagsBefore.coverage} → ${flagsAfter.coverage}, physics flags ${flagsBefore.physics} → ${flagsAfter.physics}.`,
            model_used: 'kit_render_worker'
          }
        ]);
      }
      setFixReport(null);
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

  const handleDismissFixReport = () => setFixReport(null);

  // POST /api/ingest-kit-output -> pulls in a pre-existing Omniverse Kit
  // render/capture (produced by running the real Kit app directly on the EC2
  // box, outside kit_render_worker.py) and shows it in the Kit Render Result tab
  // exactly like a subprocess-driven render.
  const handleIngestKitOutput = async (sourceDir) => {
    if (!sourceDir) return;
    setIsIngesting(true);
    setKitRenderStatus('rendering');
    setKitRenderError(null);

    const sceneId = `kit_ingest_${Date.now()}`;

    try {
      const response = await fetch('/api/ingest-kit-output', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene_id: sceneId, source_dir: sourceDir })
      });

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        throw new Error(errBody.detail || `Ingest failed with status ${response.status}`);
      }

      const data = await response.json();
      setKitRenderResult(data);
      setKitRenderStatus('done');

      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `📥 **Loaded real Kit output from \`${sourceDir}\`.**\n${(data.render_files || []).length} image(s), ${(data.video_files || []).length} video(s).`,
          model_used: 'kit_ingest'
        }
      ]);
    } catch (err) {
      console.error('Ingest kit output error:', err);
      setKitRenderError(err.message);
      setKitRenderStatus('failed');
    } finally {
      setIsIngesting(false);
    }
  };

  // Preset Loaders
  const handleLoadPreset = (presetType) => {
    let presetConfig;
    if (presetType === 'bedroom') {
      presetConfig = {
        walls: [
          { id: 'wall_north', position: [0, 3.0, 1.5], width: 8.0, height: 3.0, thickness: 0.2, rotation: 0 },
          { id: 'wall_west', position: [-4.0, 0, 1.5], width: 6.0, height: 3.0, thickness: 0.2, rotation: 90 },
          { id: 'wall_east', position: [4.0, 0, 1.5], width: 6.0, height: 3.0, thickness: 0.2, rotation: 90 }
        ],
        floor: { width: 8.0, depth: 6.0 },
        shots: [
          { shot_id: 'shot_1_establishing', focal_length_mm: 24.0, start_position: [-3.5, -2.4, 1.6], end_position: [0.5, 0.5, 1.6], duration_seconds: 5.0 },
          { shot_id: 'shot_2_medium', focal_length_mm: 50.0, start_position: [-3.0, 0.5, 1.6], end_position: [0.0, 0.0, 1.6], duration_seconds: 4.0 }
        ]
      };
      setSceneConfig(presetConfig);
      setCurrentScene(null);
      setReadyForConfirmation(true);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: 'Loaded **Bedroom 3-Wall Preset** (8m × 6m with 24mm & 50mm camera shots).',
          model_used: 'preset'
        }
      ]);
    } else if (presetType === 'corridor') {
      presetConfig = {
        walls: [
          { id: 'wall_north', position: [0, 2.0, 1.5], width: 12.0, height: 3.0, thickness: 0.2, rotation: 0 },
          { id: 'wall_south', position: [0, -2.0, 1.5], width: 12.0, height: 3.0, thickness: 0.2, rotation: 0 },
          { id: 'wall_west', position: [-6.0, 0, 1.5], width: 4.0, height: 3.0, thickness: 0.2, rotation: 90 },
          { id: 'wall_east', position: [6.0, 0, 1.5], width: 4.0, height: 3.0, thickness: 0.2, rotation: 90 }
        ],
        floor: { width: 12.0, depth: 4.0 },
        shots: [
          { shot_id: 'shot_corridor_tracking', focal_length_mm: 35.0, start_position: [-5.0, 0.0, 1.5], end_position: [5.0, 0.0, 1.5], duration_seconds: 8.0 }
        ]
      };
      setSceneConfig(presetConfig);
      setCurrentScene(null);
      setReadyForConfirmation(true);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: 'Loaded **Corridor 4-Wall Preset** (12m × 4m with tracking shot).',
          model_used: 'preset'
        }
      ]);
    }
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
        onLoadPreset={handleLoadPreset}
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
          onRenderInKit={handleRenderInKit}
          kitRenderStatus={kitRenderStatus}
          kitRenderResult={kitRenderResult}
          kitRenderError={kitRenderError}
          onGenerateFixReport={handleGenerateFixReport}
          isGeneratingReport={isGeneratingReport}
          fixReport={fixReport}
          onApplyFixReport={handleApplyFixReport}
          isApplyingFix={isApplyingFix}
          onDismissFixReport={handleDismissFixReport}
          onIngestKitOutput={handleIngestKitOutput}
          isIngesting={isIngesting}
        />
      </main>
    </div>
  );
}
