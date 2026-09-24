export interface Live2DModelInfo {
  id: string;
  name: string;
  path: string;
  version: string;
  author?: string;
  license?: string;
}

export const DEFAULT_LIVE2D_MODEL: Live2DModelInfo = {
  id: 'haru_greeter',
  name: 'Haru Greeter (春)',
  path: '/live2d/haru/haru_greeter_t03.model3.json',
  version: 'Cubism 4',
  author: 'Live2D Inc.',
  license: 'Live2D Free Material License',
};

export const LIVE2D_MODELS: Live2DModelInfo[] = [
  DEFAULT_LIVE2D_MODEL,
];

/**
 * Validates that the Live2D model manifest and core JSON files are accessible.
 */
export async function validateLive2DAssets(modelPath: string = DEFAULT_LIVE2D_MODEL.path): Promise<boolean> {
  try {
    const res = await fetch(modelPath, { method: 'HEAD' });
    return res.ok;
  } catch (err) {
    console.warn('[Live2D] Failed to probe model assets:', err);
    return false;
  }
}
