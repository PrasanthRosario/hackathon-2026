const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

async function postJson(path, payload) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail = data?.detail || data?.message || response.statusText;
    throw new Error(`Backend API ${response.status}: ${detail}`);
  }

  return data;
}

export function sendChatTurn({ messages, currentConfig, currentScene }) {
  return postJson('/chat', {
    messages,
    current_config: currentConfig,
    current_scene: currentScene
  });
}

export async function downloadUsdFromPrompt({ prompt, messages = [], outputFilename = 'agent_generated.usda' }) {
  const response = await fetch(`${API_BASE_URL}/chat-usd-file`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      messages,
      output_filename: outputFilename
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Backend API ${response.status}: ${text || response.statusText}`);
  }

  const blob = await response.blob();
  return {
    blob,
    source: response.headers.get('X-Offset-USD-Source') || 'unknown',
    sizeBytes: blob.size
  };
}

export function generateUsd({ sceneConfig, currentScene, outputFilename = 'generated_set.usda' }) {
  return postJson('/generate-usd', {
    scene_config: sceneConfig,
    scene: currentScene,
    output_filename: outputFilename
  });
}

export function checkCoverage(sceneConfig) {
  return postJson('/check-coverage', sceneConfig);
}

export function checkPhysics(sceneConfig) {
  return postJson('/check-physics', sceneConfig);
}

export function proposeFix({ currentConfig, issues }) {
  return postJson('/propose-fix', {
    current_config: currentConfig,
    issues
  });
}
