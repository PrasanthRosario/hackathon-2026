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

async function getJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);

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
    // Server-side path of the file just generated -- lets the caller point
    // /validate-usd and /list-usd-cameras at exactly this file afterward.
    path: response.headers.get('X-Offset-USD-Path') || null,
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

// POST /list-usd-cameras -> opens the given .usda with plain pxr (no Isaac
// Sim needed) and returns every real Camera prim it contains. Some USD files
// have no camera at all, so callers must handle an empty list rather than
// assuming '/World/MainCamera' exists.
export function listUsdCameras(usdaPath) {
  return postJson('/list-usd-cameras', { usda_path: usdaPath });
}

// POST /validate-usd -> kicks off a real headless Isaac Sim render+validate
// job in the backend and returns immediately with {status: 'queued', scene_id}.
// This can legitimately take minutes, so the caller polls
// getValidateSimulateStatus(sceneId) until status is 'done' or 'failed'.
export function startValidateSimulate({ usdaPath, sceneId, camera, frames, fps, renderer, warmup }) {
  return postJson('/validate-usd', {
    usda_path: usdaPath,
    scene_id: sceneId,
    ...(camera !== undefined ? { camera } : {}),
    ...(frames !== undefined ? { frames } : {}),
    ...(fps !== undefined ? { fps } : {}),
    ...(renderer !== undefined ? { renderer } : {}),
    ...(warmup !== undefined ? { warmup } : {}),
  });
}

export function getValidateSimulateStatus(sceneId) {
  return getJson(`/validate-usd/${sceneId}/status`);
}

// POST /propose-usd-fix -> reasons directly over the actual .usda text that was
// validated plus the real validation_result.json, and returns a corrected
// .usda file on disk (fixed_usda_path) rather than a mutated scene_config.
export function proposeUsdFix({ usdaPath, validationResult, outputFilename }) {
  return postJson('/propose-usd-fix', {
    usda_path: usdaPath,
    validation_result: validationResult,
    ...(outputFilename !== undefined ? { output_filename: outputFilename } : {}),
  });
}
