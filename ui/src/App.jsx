import React, { useState } from 'react';
import Header from './components/Header';
import LeftPanel from './components/LeftPanel';
import RenderView from './components/RenderView';

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Welcome to Offset! I am your pre-visualization set validation assistant for NVIDIA Omniverse. Describe your film set (e.g., "2 walls forming a corner, 4m wide, with a floor and 3m ceiling"), and I will help you refine and validate it.',
      model_used: '~anthropic/claude-haiku-latest'
    }
  ]);

  // Default scene state starts clean (no pre-extracted confirmation card)
  const [sceneConfig, setSceneConfig] = useState(null);
  const [currentModel, setCurrentModel] = useState('~anthropic/claude-haiku-latest');
  const [isLoading, setIsLoading] = useState(false);
  const [readyForConfirmation, setReadyForConfirmation] = useState(false);
  const [readableSummary, setReadableSummary] = useState(null);
  const [usdStatus, setUsdStatus] = useState(null);
  const [isGeneratingUSD, setIsGeneratingUSD] = useState(false);
  const [checkResults, setCheckResults] = useState(null);

  // Send conversational turn to FastAPI backend (/api/chat)
  const handleSendMessage = async (text) => {
    const userMsg = { role: 'user', content: text };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setIsLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: updatedMessages,
          current_config: sceneConfig
        })
      });

      if (!response.ok) {
        throw new Error(`API error ${response.status}`);
      }

      const data = await response.json();

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
      if (data.readable_summary) {
        setReadableSummary(data.readable_summary);
      }
    } catch (err) {
      console.error('Chat error:', err);
      setMessages([
        ...updatedMessages,
        {
          role: 'assistant',
          content: 'Sorry, I encountered an issue connecting to the LangChain backend. Please check backend server status.',
          model_used: 'error'
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  // POST /api/generate-usd
  const handleConfirmGenerateUSD = async () => {
    if (!sceneConfig) return;
    setIsGeneratingUSD(true);

    try {
      const response = await fetch('/api/generate-usd', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scene_config: sceneConfig,
          output_filename: 'generated_set.usda'
        })
      });

      const data = await response.json();
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
      const res = await fetch('/api/check-coverage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sceneConfig)
      });
      const data = await res.json();
      setCheckResults(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleCheckPhysics = async () => {
    if (!sceneConfig) return;
    try {
      const res = await fetch('/api/check-physics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sceneConfig)
      });
      const data = await res.json();
      setCheckResults(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleProposeFix = async () => {
    if (!sceneConfig) return;
    try {
      const res = await fetch('/api/propose-fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_config: sceneConfig,
          issues: checkResults?.issues || [{ rule: 'clearance_warning', detail: 'Camera close to wall' }]
        })
      });
      const data = await res.json();
      setCheckResults(data);
      if (data.proposed_config) {
        setSceneConfig(data.proposed_config);
      }
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
          isLoading={isLoading}
          sceneConfig={sceneConfig}
          readableSummary={readableSummary}
          readyForConfirmation={readyForConfirmation}
          onConfirmGenerateUSD={handleConfirmGenerateUSD}
          isGeneratingUSD={isGeneratingUSD}
          usdStatus={usdStatus}
          onCheckCoverage={handleCheckCoverage}
          onCheckPhysics={handleCheckPhysics}
          onProposeFix={handleProposeFix}
          checkResults={checkResults}
        />

        <RenderView
          sceneConfig={sceneConfig}
          usdStatus={usdStatus}
        />
      </main>
    </div>
  );
}
