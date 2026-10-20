import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { FlipHorizontal2, MessageSquare, X } from 'lucide-react';
import { Application, Ticker } from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';
import { playAudioElement, stopAudioElement } from '../workflow/streamingTts';
import './Live2DAvatar.css';

const POSITION_KEYS = {
  chat: 'atri.live2d.position.chat.v1',
  workflow: 'atri.live2d.position.workflow.v1',
};
const SIZE_KEY = 'atri.live2d.size.v1';
const FLIP_KEY = 'atri.live2d.flip.v1';
const DEFAULT_POSITIONS = {
  chat: { x: 0.86, y: 0.68 },
  workflow: { x: 0.84, y: 0.7 },
};
const MODEL_URL = '/api/live2d/atri_8.model3.json';
const MIN_SIZE = 60;
const MAX_SIZE = 180;

function readSize() {
  try {
    const stored = localStorage.getItem(SIZE_KEY);
    if (stored === null) return 100;
    const value = Number(stored);
    if (Number.isFinite(value)) return Math.min(MAX_SIZE, Math.max(MIN_SIZE, value));
  } catch { /* Use the default size when storage is unavailable. */ }
  return 100;
}

function readFlipped() {
  try { return localStorage.getItem(FLIP_KEY) === 'true'; }
  catch { return false; }
}

function getAvatarWidth(viewportWidth, size) {
  const baseWidth = viewportWidth <= 640
    ? Math.min(148, Math.max(104, viewportWidth * 0.31))
    : Math.min(250, Math.max(126, viewportWidth * 0.18));
  return Math.round(baseWidth * size / 100);
}

function readPosition(page) {
  try {
    const value = JSON.parse(localStorage.getItem(POSITION_KEYS[page]) || 'null');
    if (Number.isFinite(value?.x) && Number.isFinite(value?.y)) return value;
  } catch { /* Use the page default when saved state is unavailable. */ }
  return DEFAULT_POSITIONS[page];
}

function clampPosition(position, width, height, elementWidth, elementHeight) {
  const halfWidth = elementWidth / (2 * width);
  const halfHeight = elementHeight / (2 * height);
  const bottomOverflow = 20 + elementHeight * 0.12;
  const maxY = Math.max(halfHeight, 1 - halfHeight + bottomOverflow / height);
  return {
    x: Math.min(1 - halfWidth, Math.max(halfWidth, position.x)),
    y: Math.min(maxY, Math.max(halfHeight, position.y)),
  };
}

export default function Live2DAvatar({ page }) {
  const containerRef = useRef(null);
  const modelRef = useRef(null);
  const baseScaleRef = useRef(1);
  const basePositionYRef = useRef(0);
  const baseHeightRef = useRef(0);
  const bounceFrameRef = useRef(0);
  const clickBlinkRef = useRef({ remaining: 0, startedAt: null });
  const clickAudioRef = useRef(null);
  const dragRef = useRef(null);
  const settingsPanelRef = useRef(null);
  const [positions, setPositions] = useState(() => ({ chat: readPosition('chat'), workflow: readPosition('workflow') }));
  const [size, setSize] = useState(readSize);
  const [isFlipped, setIsFlipped] = useState(readFlipped);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [settingsMenu, setSettingsMenu] = useState(null);
  const [loadError, setLoadError] = useState('');
  const position = positions[page] || DEFAULT_POSITIONS.chat;
  const avatarWidth = getAvatarWidth(viewportWidth, size);
  const positionStyle = useMemo(() => ({
    left: `${position.x * 100}vw`,
    top: `${position.y * 100}vh`,
    width: `${avatarWidth}px`,
  }), [position, avatarWidth]);

  useEffect(() => {
    let disposed = false;
    let resizeObserver;
    let loadedModel;
    let clickBlinkListener;
    const container = containerRef.current;
    if (!container) return undefined;
    setLoadError('');

    if (!window.Live2DCubismCore) {
      setLoadError('Live2D Core 未加载，请运行 npm run download:cubism-core');
      return undefined;
    }

    Live2DModel.registerTicker(Ticker);
    const app = new Application({
      width: 1,
      height: 1,
      antialias: true,
      autoDensity: true,
      backgroundAlpha: 0,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
    });
    const canvas = app.view;
    canvas.setAttribute('aria-hidden', 'true');
    container.appendChild(canvas);

    const loadModel = async () => {
      try {
        const model = await Live2DModel.from(MODEL_URL, { autoInteract: false });
        if (disposed) {
          model.destroy({ children: true });
          return;
        }
        loadedModel = model;
        model.anchor.set(0.5, 0.5);
        modelRef.current = model;
        app.stage.addChild(model);

        clickBlinkListener = () => {
          const blink = clickBlinkRef.current;
          if (blink.remaining <= 0) return;

          const now = performance.now();
          if (blink.startedAt === null) blink.startedAt = now;
          const elapsed = now - blink.startedAt;
          let openness = 1;
          if (elapsed >= 0 && elapsed < 65) {
            const progress = elapsed / 65;
            const eased = progress * progress * (3 - 2 * progress);
            openness = 1 - eased;
          } else if (elapsed >= 65 && elapsed < 95) {
            openness = 0;
          } else if (elapsed >= 95 && elapsed < 230) {
            const progress = (elapsed - 95) / 135;
            const eased = progress * progress * (3 - 2 * progress);
            openness = eased;
          } else if (elapsed >= 230) {
            blink.remaining -= 1;
            blink.startedAt = blink.remaining > 0 ? now + 70 : null;
          }

          const coreModel = model.internalModel.coreModel;
          coreModel.setParameterValueById('ParamEyeLOpen', openness);
          coreModel.setParameterValueById('ParamEyeROpen', openness);
        };
        model.internalModel.on('beforeModelUpdate', clickBlinkListener);

        const naturalWidth = model.width;
        const naturalHeight = model.height;
        const resize = () => {
          if (!container.clientWidth || !container.clientHeight) return;
          app.renderer.resize(container.clientWidth, container.clientHeight);
          model.position.set(container.clientWidth / 2, container.clientHeight / 2);
          const fitScale = Math.min(container.clientWidth / naturalWidth, container.clientHeight / naturalHeight);
          baseScaleRef.current = fitScale;
          basePositionYRef.current = container.clientHeight / 2;
          baseHeightRef.current = naturalHeight * fitScale;
          model.scale.set(fitScale);
        };
        resize();
        resizeObserver = new ResizeObserver(resize);
        resizeObserver.observe(container);
      } catch (error) {
        if (!disposed) setLoadError(error?.message || 'Live2D 模型加载失败');
      }
    };
    loadModel();

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      cancelAnimationFrame(bounceFrameRef.current);
      if (loadedModel && clickBlinkListener) {
        loadedModel.internalModel.off('beforeModelUpdate', clickBlinkListener);
      }
      modelRef.current = null;
      if (canvas.parentElement === container) container.removeChild(canvas);
      app.destroy(true, { children: true });
    };
  }, []);

  useEffect(() => () => {
    cancelAnimationFrame(bounceFrameRef.current);
    stopAudioElement(clickAudioRef.current);
    clickAudioRef.current = null;
  }, []);

  useEffect(() => {
    const clampToViewport = () => {
      const element = containerRef.current;
      if (!element) return;
      setViewportWidth(window.innerWidth);
      setPositions((current) => {
        const next = clampPosition(current[page], window.innerWidth, window.innerHeight, element.offsetWidth, element.offsetHeight);
        if (next.x === current[page].x && next.y === current[page].y) return current;
        try { localStorage.setItem(POSITION_KEYS[page], JSON.stringify(next)); } catch { /* Keep the session position if storage is unavailable. */ }
        return { ...current, [page]: next };
      });
    };
    window.addEventListener('resize', clampToViewport);
    clampToViewport();
    return () => window.removeEventListener('resize', clampToViewport);
  }, [page, avatarWidth]);

  useEffect(() => {
    setSettingsMenu(null);
  }, [page]);

  useEffect(() => {
    if (!settingsMenu) return undefined;
    const closeOnOutsidePointer = (event) => {
      if (!settingsPanelRef.current?.contains(event.target)) setSettingsMenu(null);
    };
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setSettingsMenu(null);
    };
    const closeOnResize = () => setSettingsMenu(null);
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    window.addEventListener('keydown', closeOnEscape);
    window.addEventListener('resize', closeOnResize);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer);
      window.removeEventListener('keydown', closeOnEscape);
      window.removeEventListener('resize', closeOnResize);
    };
  }, [settingsMenu]);

  const savePosition = (pageKey, next) => {
    setPositions((current) => ({ ...current, [pageKey]: next }));
    try { localStorage.setItem(POSITION_KEYS[pageKey], JSON.stringify(next)); } catch { /* Keep the session position if storage is unavailable. */ }
  };

  const saveSize = (next) => {
    setSize(next);
    try { localStorage.setItem(SIZE_KEY, String(next)); } catch { /* Keep the session size if storage is unavailable. */ }
  };

  const toggleFlip = () => {
    const next = !isFlipped;
    setIsFlipped(next);
    try { localStorage.setItem(FLIP_KEY, String(next)); } catch { /* Keep the session setting if storage is unavailable. */ }
  };

  const openSettingsAt = (clientX, clientY) => {
    const menuWidth = Math.min(248, window.innerWidth - 16);
    const menuHeight = Math.min(164, window.innerHeight - 16);
    const gap = 8;
    let preferredX = clientX + gap;
    let preferredY = clientY + gap;
    if (preferredX + menuWidth > window.innerWidth - gap) preferredX = clientX - menuWidth - gap;
    if (preferredY + menuHeight > window.innerHeight - gap) preferredY = clientY - menuHeight - gap;
    setSettingsMenu({
      x: Math.max(8, Math.min(preferredX, window.innerWidth - menuWidth - 8)),
      y: Math.max(8, Math.min(preferredY, window.innerHeight - menuHeight - 8)),
    });
  };

  const handleContextMenu = (event) => {
    event.preventDefault();
    openSettingsAt(event.clientX, event.clientY);
  };

  const bounce = () => {
    const model = modelRef.current;
    if (!model) return;
    cancelAnimationFrame(bounceFrameRef.current);
    const start = performance.now();
    const baseScale = baseScaleRef.current;
    const animate = (now) => {
      const progress = Math.min(1, (now - start) / 760);
      const spring = Math.exp(-7.2 * progress) * Math.cos(19 * progress);
      const scaleY = 1 - 0.17 * spring;
      model.scale.set(baseScale * (1 + 0.07 * spring), baseScale * scaleY);
      // Keep the model's bottom edge fixed while the top compresses and rebounds.
      model.position.y = basePositionYRef.current + baseHeightRef.current * (1 - scaleY) / 2;
      if (progress < 1) bounceFrameRef.current = requestAnimationFrame(animate);
      else {
        model.scale.set(baseScale);
        model.position.y = basePositionYRef.current;
      }
    };
    bounceFrameRef.current = requestAnimationFrame(animate);
  };

  const triggerInteraction = () => {
    const blink = clickBlinkRef.current;
    blink.remaining = Math.min(blink.remaining + 1, 12);
    if (blink.startedAt === null) blink.startedAt = performance.now();
    const previousAudio = clickAudioRef.current;
    if (previousAudio) {
      stopAudioElement(previousAudio);
    }
    const audio = new Audio(`/api/live2d/click-audio?request=${Date.now()}`);
    clickAudioRef.current = audio;
    const clearAudio = () => {
      if (clickAudioRef.current === audio) clickAudioRef.current = null;
    };
    audio.addEventListener('ended', clearAudio, { once: true });
    audio.addEventListener('error', () => {
      clearAudio();
      stopAudioElement(audio);
    }, { once: true });
    playAudioElement(audio).catch(clearAudio);
    bounce();
  };

  const handlePointerDown = (event) => {
    if (event.button !== 0) return;
    dragRef.current = {
      pointerId: event.pointerId,
      page,
      startX: event.clientX,
      startY: event.clientY,
      position,
      lastPosition: position,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < 7) return;
    drag.moved = true;
    drag.lastPosition = clampPosition({
      x: drag.position.x + dx / window.innerWidth,
      y: drag.position.y + dy / window.innerHeight,
    }, window.innerWidth, window.innerHeight, event.currentTarget.offsetWidth, event.currentTarget.offsetHeight);
    setPositions((current) => ({ ...current, [drag.page]: drag.lastPosition }));
  };

  const handlePointerUp = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag.moved) savePosition(drag.page, drag.lastPosition);
    else triggerInteraction();
  };

  const handlePointerCancel = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (drag.moved) savePosition(drag.page, drag.lastPosition);
  };

  const handleKeyDown = (event) => {
    if (event.key === 'ContextMenu' || (event.key === 'F10' && event.shiftKey)) {
      event.preventDefault();
      const bounds = event.currentTarget.getBoundingClientRect();
      openSettingsAt(bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
      return;
    }
    if (event.key === 'Escape' && settingsMenu) {
      setSettingsMenu(null);
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      triggerInteraction();
      return;
    }
    const increments = { ArrowLeft: [-0.015, 0], ArrowRight: [0.015, 0], ArrowUp: [0, -0.015], ArrowDown: [0, 0.015] };
    if (!increments[event.key]) return;
    event.preventDefault();
    const [dx, dy] = increments[event.key];
    const element = containerRef.current;
    const next = clampPosition({ x: position.x + dx, y: position.y + dy }, window.innerWidth, window.innerHeight, element.offsetWidth, element.offsetHeight);
    savePosition(page, next);
  };

  return (
    <>
      <div
        ref={containerRef}
        className={`live2d-avatar ${isFlipped ? 'is-flipped' : ''} ${loadError ? 'has-error' : ''}`}
        style={positionStyle}
        role="button"
        tabIndex={0}
        aria-label="ATRI Live2D 形象。拖动可移动，点击可互动。"
        aria-haspopup="dialog"
        title="拖动移动 · 点击互动并播放语音 · 右键设置"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        onKeyDown={handleKeyDown}
        onContextMenu={handleContextMenu}
      >
        {loadError && <div className="live2d-avatar-error" role="status">{loadError}</div>}
      </div>
      {settingsMenu && createPortal(
        <div
          ref={settingsPanelRef}
          className="live2d-settings-menu"
          role="dialog"
          aria-label="小人设置"
          style={{ left: `${settingsMenu.x}px`, top: `${settingsMenu.y}px` }}
          onPointerDown={(event) => event.stopPropagation()}
          onKeyDown={(event) => {
            event.stopPropagation();
            if (event.key === 'Escape') setSettingsMenu(null);
          }}
        >
          <header className="live2d-settings-header">
            <strong>角色设置</strong>
            <button type="button" className="live2d-settings-close" aria-label="关闭设置" onClick={() => setSettingsMenu(null)}>
              <X size={15} aria-hidden="true" />
            </button>
          </header>
          <label className="live2d-size-control" htmlFor={`live2d-avatar-size-${page}`}>
            <span className="live2d-size-label">
              <span>小人大小</span>
              <output>{size}%</output>
            </span>
            <input
              id={`live2d-avatar-size-${page}`}
              type="range"
              min={MIN_SIZE}
              max={MAX_SIZE}
              step="5"
              value={size}
              onChange={(event) => saveSize(Number(event.target.value))}
            />
          </label>
          <div className="live2d-settings-actions">
            <button
              type="button"
              className={`live2d-settings-action ${isFlipped ? 'is-active' : ''}`}
              aria-pressed={isFlipped}
              onClick={toggleFlip}
            >
              <FlipHorizontal2 size={15} aria-hidden="true" />
              <span>反转小人</span>
            </button>
            <button
              type="button"
              className="live2d-settings-action is-reserved"
              title="预留"
              disabled
            >
              <MessageSquare size={15} aria-hidden="true" />
              <span>反转消息框</span>
            </button>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
