import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Play, Pause, Eye, Camera, EyeOff } from 'lucide-react';

export default function ThreeCanvas({ sceneConfig }) {
  const containerRef = useRef(null);
  const sceneRef = useRef(null);
  const rendererRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  
  const cameraMeshRef = useRef(null);
  const frustumHelperRef = useRef(null);
  const animFrameIdRef = useRef(null);

  const [isPlaying, setIsPlaying] = useState(true);
  const [showFrustum, setShowFrustum] = useState(true);
  const [activeShotIndex, setActiveShotIndex] = useState(0);
  const [animProgress, setAnimProgress] = useState(0);

  // Initialize Studio Three.js Scene
  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const width = container.clientWidth;
    const height = container.clientHeight;

    // 1. Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#0E1420');
    scene.fog = new THREE.FogExp2('#0E1420', 0.025);
    sceneRef.current = scene;

    // 2. Camera
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(12, 12, 10);
    camera.lookAt(0, 0, 1.5);
    cameraRef.current = camera;

    // 3. Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // 4. Orbit Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.maxPolarAngle = Math.PI / 2 + 0.02; // Floor boundary
    controlsRef.current = controls;

    // 5. Studio Lighting Setup
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xfff5ea, 1.8);
    keyLight.position.set(15, 20, 15);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.width = 2048;
    keyLight.shadow.mapSize.height = 2048;
    keyLight.shadow.bias = -0.0001;
    scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0x38bdf8, 0.6);
    fillLight.position.set(-15, -10, 12);
    scene.add(fillLight);

    const rimLight = new THREE.DirectionalLight(0xf54e00, 0.8);
    rimLight.position.set(0, -20, 10);
    scene.add(rimLight);

    // Resize Handler
    const handleResize = () => {
      if (!containerRef.current || !rendererRef.current || !cameraRef.current) return;
      const w = containerRef.current.clientWidth;
      const h = containerRef.current.clientHeight;
      cameraRef.current.aspect = w / h;
      cameraRef.current.updateProjectionMatrix();
      rendererRef.current.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    // Render Animation Loop
    const animate = () => {
      animFrameIdRef.current = requestAnimationFrame(animate);
      if (controlsRef.current) controlsRef.current.update();
      if (rendererRef.current && sceneRef.current && cameraRef.current) {
        rendererRef.current.render(sceneRef.current, cameraRef.current);
      }
    };
    animate();

    return () => {
      window.removeEventListener('resize', handleResize);
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
      if (rendererRef.current && rendererRef.current.domElement) {
        container.removeChild(rendererRef.current.domElement);
        rendererRef.current.dispose();
      }
    };
  }, []);

  // Update Meshes & Camera Path whenever sceneConfig changes
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !sceneConfig) return;

    // Clear dynamic meshes
    const toRemove = [];
    scene.children.forEach(child => {
      if (child.type === 'Mesh' || child.type === 'Group' || child.type === 'Line' || child.type === 'GridHelper') {
        toRemove.push(child);
      }
    });
    toRemove.forEach(obj => scene.remove(obj));

    const { floor, walls, shots } = sceneConfig;

    // 1. Render Floor Grid & Base Mesh
    if (floor) {
      const fWidth = floor.width || 8.0;
      const fDepth = floor.depth || 6.0;

      // Studio Floor Surface
      const floorGeo = new THREE.PlaneGeometry(fWidth, fDepth);
      const floorMat = new THREE.MeshStandardMaterial({
        color: 0x1E293B,
        roughness: 0.4,
        metalness: 0.2,
        side: THREE.DoubleSide
      });
      const floorMesh = new THREE.Mesh(floorGeo, floorMat);
      floorMesh.rotation.x = -Math.PI / 2;
      floorMesh.position.set(0, 0, 0);
      floorMesh.receiveShadow = true;
      scene.add(floorMesh);

      // Metallic Studio Grid
      const gridHelper = new THREE.GridHelper(Math.max(fWidth, fDepth) * 1.5, 24, 0x38BDF8, 0x334155);
      gridHelper.position.y = 0.01;
      scene.add(gridHelper);
    }

    // 2. Render Wall Meshes (Architectural Plaster Finish)
    if (walls && walls.length > 0) {
      walls.forEach((wall, idx) => {
        const wWidth = wall.width || 4.0;
        const wHeight = wall.height || 3.0;
        const wThick = wall.thickness || 0.2;
        const [x, y, z] = wall.position || [0, 0, wHeight / 2];

        const wallGeo = new THREE.BoxGeometry(wWidth, wHeight, wThick);
        
        // Architectural Wall Material
        const wallMat = new THREE.MeshStandardMaterial({
          color: 0xE2E8F0,
          roughness: 0.6,
          metalness: 0.05
        });
        const wallMesh = new THREE.Mesh(wallGeo, wallMat);

        // Subtle dark metallic edge lines
        const edges = new THREE.EdgesGeometry(wallGeo);
        const lineMat = new THREE.LineBasicMaterial({ color: 0x475569, linewidth: 1 });
        const wireframe = new THREE.LineSegments(edges, lineMat);
        wallMesh.add(wireframe);

        // Convert Z-up to Three.js Y-up coordinates: [X, Y, Z] -> [X, Z, -Y]
        wallMesh.position.set(x, z, -y);
        const rotRad = ((wall.rotation || 0) * Math.PI) / 180;
        wallMesh.rotation.y = -rotRad;

        wallMesh.castShadow = true;
        wallMesh.receiveShadow = true;
        scene.add(wallMesh);
      });
    }

    // 3. Render Camera Path & Shot Frustum
    if (shots && shots.length > 0) {
      const activeShot = shots[activeShotIndex] || shots[0];
      const [sx, sy, sz] = activeShot.start_position || [-3, -2, 1.6];
      const [ex, ey, ez] = activeShot.end_position || [1, 0, 1.6];

      const pStart = new THREE.Vector3(sx, sz, -sy);
      const pEnd = new THREE.Vector3(ex, ez, -ey);

      // Camera Motion Line Spline
      const pathGeo = new THREE.BufferGeometry().setFromPoints([pStart, pEnd]);
      const pathMat = new THREE.LineDashedMaterial({
        color: 0xF54E00,
        dashSize: 0.3,
        gapSize: 0.15,
        linewidth: 3
      });
      const pathLine = new THREE.Line(pathGeo, pathMat);
      pathLine.computeLineDistances();
      scene.add(pathLine);

      // Camera Cinema Rig Group
      const camGroup = new THREE.Group();
      
      const camBoxGeo = new THREE.BoxGeometry(0.45, 0.35, 0.55);
      const camBoxMat = new THREE.MeshStandardMaterial({ color: 0x0F172A, metalness: 0.8, roughness: 0.2 });
      const camBox = new THREE.Mesh(camBoxGeo, camBoxMat);
      camGroup.add(camBox);

      // Glass Lens Element
      const lensGeo = new THREE.CylinderGeometry(0.14, 0.14, 0.3, 16);
      const lensMat = new THREE.MeshStandardMaterial({ color: 0xF54E00, metalness: 0.9, roughness: 0.1 });
      const lens = new THREE.Mesh(lensGeo, lensMat);
      lens.rotation.x = Math.PI / 2;
      lens.position.z = -0.35;
      camGroup.add(lens);

      camGroup.position.copy(pStart);
      camGroup.lookAt(pEnd);
      scene.add(camGroup);
      cameraMeshRef.current = camGroup;

      // Glowing Frustum Pyramid Wireframe
      const focalLength = activeShot.focal_length_mm || 35.0;
      const hAperture = 36.0;
      const fovRad = 2 * Math.atan((hAperture / 2) / focalLength);
      const frustumDistance = 4.5;
      const halfW = frustumDistance * Math.tan(fovRad / 2);
      const halfH = halfW * 0.75;

      const frustumGeo = new THREE.BufferGeometry();
      const vertices = new Float32Array([
        0, 0, 0,  -halfW, halfH, -frustumDistance,
        0, 0, 0,   halfW, halfH, -frustumDistance,
        0, 0, 0,   halfW, -halfH, -frustumDistance,
        0, 0, 0,  -halfW, -halfH, -frustumDistance,
        -halfW, halfH, -frustumDistance,   halfW, halfH, -frustumDistance,
         halfW, halfH, -frustumDistance,   halfW, -halfH, -frustumDistance,
         halfW, -halfH, -frustumDistance, -halfW, -halfH, -frustumDistance,
        -halfW, -halfH, -frustumDistance, -halfW, halfH, -frustumDistance,
      ]);
      frustumGeo.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
      const frustumMat = new THREE.LineBasicMaterial({ color: 0xF1A80A, linewidth: 2 });
      const frustumLines = new THREE.LineSegments(frustumGeo, frustumMat);
      
      camGroup.add(frustumLines);
      frustumHelperRef.current = frustumLines;
    }
  }, [sceneConfig, activeShotIndex]);

  // Camera Animation Loop
  useEffect(() => {
    if (!isPlaying || !sceneConfig?.shots || sceneConfig.shots.length === 0) return;

    const shot = sceneConfig.shots[activeShotIndex] || sceneConfig.shots[0];
    const duration = (shot.duration_seconds || 5.0) * 1000;
    const [sx, sy, sz] = shot.start_position;
    const [ex, ey, ez] = shot.end_position;

    const pStart = new THREE.Vector3(sx, sz, -sy);
    const pEnd = new THREE.Vector3(ex, ez, -ey);

    let startTime = performance.now();
    let animId;

    const updatePosition = (now) => {
      const elapsed = (now - startTime) % duration;
      const progress = elapsed / duration;
      setAnimProgress(progress);

      if (cameraMeshRef.current) {
        cameraMeshRef.current.position.lerpVectors(pStart, pEnd, progress);
        cameraMeshRef.current.lookAt(pEnd);
      }

      animId = requestAnimationFrame(updatePosition);
    };

    animId = requestAnimationFrame(updatePosition);
    return () => cancelAnimationFrame(animId);
  }, [isPlaying, sceneConfig, activeShotIndex]);

  useEffect(() => {
    if (frustumHelperRef.current) {
      frustumHelperRef.current.visible = showFrustum;
    }
  }, [showFrustum]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

      {/* Floating Control Glass Overlay */}
      <div style={{
        position: 'absolute',
        bottom: '20px',
        left: '20px',
        right: '20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        pointerEvents: 'none'
      }}>
        {/* Play/Pause & Camera Controls */}
        <div className="ph-card" style={{
          padding: '8px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          pointerEvents: 'auto'
        }}>
          <button 
            className="ph-btn ph-btn-sm ph-btn-primary"
            onClick={() => setIsPlaying(!isPlaying)}
          >
            {isPlaying ? <Pause size={14} /> : <Play size={14} />}
            <span>{isPlaying ? 'Pause' : 'Play'}</span>
          </button>

          <button 
            className={`ph-btn ph-btn-sm ${showFrustum ? 'ph-btn-yellow' : ''}`}
            onClick={() => setShowFrustum(!showFrustum)}
            title="Toggle Frustum FOV"
          >
            {showFrustum ? <Eye size={14} /> : <EyeOff size={14} />}
            <span>Frustum FOV</span>
          </button>
        </div>

        {/* Shot List Selector */}
        {sceneConfig?.shots && sceneConfig.shots.length > 0 && (
          <div className="ph-card" style={{
            padding: '8px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            pointerEvents: 'auto'
          }}>
            <Camera size={14} style={{ color: 'var(--accent-orange)' }} />
            <span>Shot:</span>
            <select 
              value={activeShotIndex}
              onChange={(e) => setActiveShotIndex(Number(e.target.value))}
              style={{
                padding: '4px 10px',
                border: '1px solid var(--border-subtle)',
                borderRadius: '6px',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                fontWeight: 600,
                backgroundColor: 'var(--bg-surface-elevated)',
                color: '#FFF',
                outline: 'none'
              }}
            >
              {sceneConfig.shots.map((shot, idx) => (
                <option key={shot.shot_id || idx} value={idx}>
                  {shot.shot_id} ({shot.focal_length_mm}mm)
                </option>
              ))}
            </select>

            <span style={{ color: 'var(--text-muted)' }}>
              Progress: {Math.round(animProgress * 100)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
