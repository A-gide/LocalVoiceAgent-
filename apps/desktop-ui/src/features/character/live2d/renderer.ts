import { DEFAULT_LIVE2D_MODEL } from './manifest';

export class Live2DRenderer {
  private app: any = null;
  private model: any = null;
  private canvas: HTMLCanvasElement | null = null;
  private isDestroyed = false;
  public isReady = false;
  public hasError = false;
  public errorMessage = '';

  /**
   * Initialize PIXI Application and load the Live2D model onto the provided canvas.
   */
  async init(canvas: HTMLCanvasElement, modelPath: string = DEFAULT_LIVE2D_MODEL.path): Promise<boolean> {
    this.canvas = canvas;
    this.isDestroyed = false;
    this.isReady = false;
    this.hasError = false;

    const pixi = (window as any).PIXI;
    if (!pixi || !pixi.live2d) {
      this.hasError = true;
      this.errorMessage = 'PIXI or PIXI.live2d runtime not found';
      console.warn('[Live2D] Runtime not available:', this.errorMessage);
      return false;
    }

    try {
      const rect = canvas.getBoundingClientRect();
      const width = rect.width || 300;
      const height = rect.height || 400;

      this.app = new pixi.Application({
        view: canvas,
        transparent: true,
        width,
        height,
        backgroundAlpha: 0,
        antialias: true,
        autoDensity: true,
        resolution: window.devicePixelRatio || 1,
      });

      const Live2DModel = pixi.live2d.Live2DModel;
      this.model = await Live2DModel.from(modelPath, {
        autoInteract: false,
      });

      if (this.isDestroyed) {
        this.destroy();
        return false;
      }

      this.app.stage.addChild(this.model);
      this.fit(width, height);

      // Play default idle motion
      try {
        this.model.motion('Idle');
      } catch (e) {
        // Some models have different motion groups
      }

      this.isReady = true;
      return true;
    } catch (err: any) {
      this.hasError = true;
      this.errorMessage = err?.message || 'Failed to initialize Live2D model';
      console.error('[Live2D] Initialization failed:', err);
      return false;
    }
  }

  /**
   * Responsive fit and anchoring of the model inside the canvas viewport.
   */
  fit(width: number, height: number): void {
    if (!this.model || !this.isReady) return;
    try {
      const scale = Math.min(width / (this.model.width || 300), height / (this.model.height || 400)) * 1.5;
      this.model.scale.set(scale);
      this.model.x = width / 2;
      this.model.y = height * 0.92;
      this.model.anchor.set(0.5, 1);
    } catch (e) {
      console.warn('[Live2D] Fit error:', e);
    }
  }

  /**
   * Set mouth opening parameter for lip sync.
   * @param level normalized level [0.0 - 1.0]
   */
  setMouth(level: number): void {
    if (!this.model || !this.isReady) return;
    try {
      const cm = this.model.internalModel?.coreModel;
      if (cm && typeof cm.setParameterValueById === 'function') {
        const openVal = Math.min(1.0, Math.max(0.0, level * 2.5));
        cm.setParameterValueById('ParamMouthOpenY', openVal);
        cm.setParameterValueById('ParamMouthForm', level > 0.05 ? 1 : 0);
      }
    } catch (e) {
      // Ignore transient parameter update errors
    }
  }

  /**
   * Trigger an expression by index or name.
   */
  setExpression(expr: number | string): void {
    if (!this.model || !this.isReady) return;
    try {
      if (typeof this.model.expression === 'function') {
        this.model.expression(expr);
      }
    } catch (e) {
      console.warn('[Live2D] Expression error:', e);
    }
  }

  /**
   * Trigger a motion group (e.g. 'Idle', 'TapBody').
   */
  setMotion(group: string): void {
    if (!this.model || !this.isReady) return;
    try {
      if (typeof this.model.motion === 'function') {
        this.model.motion(group);
      }
    } catch (e) {
      console.warn('[Live2D] Motion error:', e);
    }
  }

  /**
   * Clean up WebGL resources, models, and PIXI application.
   */
  destroy(): void {
    this.isDestroyed = true;
    this.isReady = false;

    if (this.model) {
      try {
        this.model.destroy();
      } catch (e) {}
      this.model = null;
    }

    if (this.app) {
      try {
        this.app.destroy(false, {
          children: true,
          texture: true,
          baseTexture: true,
        });
      } catch (e) {}
      this.app = null;
    }

    this.canvas = null;
  }
}
