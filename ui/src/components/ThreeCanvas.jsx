import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Play, Pause, Eye, Camera, EyeOff } from 'lucide-react';

const MATERIAL_COLORS = {
  acoustic_panel: 0x293241,
  bed: 0x6b7280,
  chair: 0x394a5f,
  church: 0x7d7874,
  crowd: 0x9ca3af,
  hero: 0xffffff,
  microphone: 0x181c20,
  person: 0x9ca3af,
  plant: 0x2f855a,
  shelf: 0x6b4f3a,
  table: 0x6f4528,
  tree: 0x2f6f3e
};

function zUpToThreePosition(position = [0, 0, 0]) {
  const [x, y, z] = position;
  return new THREE.Vector3(x, z, -y);
}

function zUpRotationToThree(rotation = [0, 0, 0]) {
  const [rx, ry, rz] = rotation;
  return new THREE.Euler(
    THREE.MathUtils.degToRad(rx),
    -THREE.MathUtils.degToRad(rz),
    THREE.MathUtils.degToRad(ry)
  );
}

function parseColor(color, fallback) {
  if (!color) return fallback;
  return new THREE.Color(color);
}

function semanticText(object) {
  return `${object.id} ${object.name} ${object.kind} ${(object.tags || []).join(' ')}`.toLowerCase();
}

function isPersonObject(object) {
  const text = semanticText(object);
  return ['person', 'hero', 'crowd', 'actor', 'extra', 'villager', 'pedestrian'].some(token => text.includes(token));
}

function isTreeObject(object) {
  const text = semanticText(object);
  return ['tree', 'oak', 'palm', 'foliage'].some(token => text.includes(token));
}

function isChurchObject(object) {
  const text = semanticText(object);
  return ['church', 'chapel', 'cathedral'].some(token => text.includes(token));
}

function createPersonGroup(object) {
  const text = semanticText(object);
  const isHero = text.includes('hero');
  const baseColor = isHero ? 0xffffff : (MATERIAL_COLORS[object.kind] || 0x4f8bc9);
  const clothing = parseColor(object.material?.color, baseColor);
  const skin = new THREE.Color(0xd7a47c);
  const dark = new THREE.Color(0x1f2933);
  const group = new THREE.Group();
  group.name = object.id;

  const body = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.16, 0.78, 6, 12),
    new THREE.MeshStandardMaterial({ color: clothing, roughness: 0.72 })
  );
  body.position.y = 0.82;
  group.add(body);

  const head = new THREE.Mesh(
    new THREE.SphereGeometry(0.17, 20, 14),
    new THREE.MeshStandardMaterial({ color: skin, roughness: 0.65 })
  );
  head.position.y = 1.45;
  group.add(head);

  const hair = new THREE.Mesh(
    new THREE.SphereGeometry(0.175, 16, 8, 0, Math.PI * 2, 0, Math.PI * 0.45),
    new THREE.MeshStandardMaterial({ color: dark, roughness: 0.8 })
  );
  hair.position.y = 1.55;
  group.add(hair);

  const limbMat = new THREE.MeshStandardMaterial({ color: isHero ? 0xf7f7f2 : dark, roughness: 0.75 });
  [
    [-0.09, 0.22],
    [0.09, 0.22],
    [-0.22, 0.84],
    [0.22, 0.84]
  ].forEach(([x, y], index) => {
    const limb = new THREE.Mesh(new THREE.CapsuleGeometry(0.035, 0.38, 4, 8), limbMat);
    limb.position.set(x, y, 0);
    limb.rotation.z = index < 2 ? 0.08 * Math.sign(x) : 0.35 * Math.sign(x);
    group.add(limb);
  });

  if (isHero) {
    const marker = new THREE.Mesh(
      new THREE.TorusGeometry(0.34, 0.012, 8, 40),
      new THREE.MeshStandardMaterial({ color: 0xf1a80a, emissive: 0x6b4a00, roughness: 0.4 })
    );
    marker.rotation.x = Math.PI / 2;
    marker.position.y = 0.03;
    group.add(marker);
  }

  group.position.copy(zUpToThreePosition(object.transform?.position));
  group.rotation.copy(zUpRotationToThree(object.transform?.rotation));
  group.scale.set(...(object.transform?.scale || [1, 1, 1]));
  group.traverse(child => {
    if (child.isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });
  return group;
}

function createTreeGroup(object) {
  const group = new THREE.Group();
  group.name = object.id;
  const trunk = new THREE.Mesh(
    new THREE.CylinderGeometry(0.09, 0.13, 1.15, 10),
    new THREE.MeshStandardMaterial({ color: 0x6b4a2f, roughness: 0.9 })
  );
  trunk.position.y = 0.58;
  group.add(trunk);

  const foliageMaterial = new THREE.MeshStandardMaterial({
    color: parseColor(object.material?.color, 0x2f7d42),
    roughness: 0.9
  });
  [
    [0, 1.35, 0, 0.48],
    [-0.22, 1.1, 0.08, 0.34],
    [0.22, 1.14, -0.06, 0.34]
  ].forEach(([x, y, z, radius]) => {
    const foliage = new THREE.Mesh(new THREE.SphereGeometry(radius, 18, 14), foliageMaterial);
    foliage.position.set(x, y, z);
    group.add(foliage);
  });

  group.position.copy(zUpToThreePosition(object.transform?.position));
  group.rotation.copy(zUpRotationToThree(object.transform?.rotation));
  group.scale.set(...(object.transform?.scale || [1, 1, 1]));
  group.traverse(child => {
    if (child.isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });
  return group;
}

function createChurchGroup(object) {
  const [sx = 5, sy = 7, sz = 4] = object.geometry?.size || [];
  const group = new THREE.Group();
  group.name = object.id;
  const stone = new THREE.MeshStandardMaterial({
    color: parseColor(object.material?.color, 0x8c8782),
    roughness: 0.86
  });
  const roofMat = new THREE.MeshStandardMaterial({ color: 0x3a312e, roughness: 0.78 });

  const nave = new THREE.Mesh(new THREE.BoxGeometry(sx, Math.max(2.5, sz * 0.62), sy), stone);
  nave.position.y = Math.max(2.5, sz * 0.62) / 2;
  group.add(nave);

  const roof = new THREE.Mesh(new THREE.ConeGeometry(sx * 0.68, 1.2, 4), roofMat);
  roof.position.y = Math.max(2.5, sz * 0.62) + 0.55;
  roof.rotation.y = Math.PI / 4;
  roof.scale.z = sy / sx;
  group.add(roof);

  const tower = new THREE.Mesh(new THREE.BoxGeometry(sx * 0.32, sz * 0.95, sx * 0.32), stone);
  tower.position.set(0, sz * 0.48, -sy * 0.38);
  group.add(tower);

  const steeple = new THREE.Mesh(new THREE.ConeGeometry(sx * 0.22, sz * 0.7, 4), roofMat);
  steeple.position.set(0, sz * 1.08, -sy * 0.38);
  steeple.rotation.y = Math.PI / 4;
  group.add(steeple);

  const door = new THREE.Mesh(
    new THREE.BoxGeometry(sx * 0.22, 1.35, 0.06),
    new THREE.MeshStandardMaterial({ color: 0x2d1b16, roughness: 0.7 })
  );
  door.position.set(0, 0.68, -sy / 2 - 0.035);
  group.add(door);

  group.position.copy(zUpToThreePosition(object.transform?.position));
  group.rotation.copy(zUpRotationToThree(object.transform?.rotation));
  group.scale.set(...(object.transform?.scale || [1, 1, 1]));
  group.traverse(child => {
    if (child.isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });
  return group;
}

function createSemanticObject(object) {
  if (isPersonObject(object)) return createPersonGroup(object);
  if (isTreeObject(object)) return createTreeGroup(object);
  if (isChurchObject(object)) return createChurchGroup(object);
  return null;
}

function createSceneObjectMesh(object) {
  const semanticObject = createSemanticObject(object);
  if (semanticObject) return semanticObject;

  const geometry = object.geometry || {};
  const [sx = 1, sy = 1, sz = 1] = geometry.size || [1, 1, 1];
  let meshGeometry;

  if (geometry.type === 'cylinder') {
    const radius = geometry.radius || sx || 0.1;
    const height = geometry.height || sz || 1;
    meshGeometry = new THREE.CylinderGeometry(radius, radius, height, 24);
  } else if (geometry.type === 'sphere') {
    meshGeometry = new THREE.SphereGeometry(geometry.radius || sx || 0.5, 24, 16);
  } else if (geometry.type === 'plane') {
    meshGeometry = new THREE.PlaneGeometry(sx, sy);
  } else {
    meshGeometry = new THREE.BoxGeometry(sx, sz, sy);
  }

  const baseColor = MATERIAL_COLORS[object.kind] || 0x9ca3af;
  const material = new THREE.MeshStandardMaterial({
    color: parseColor(object.material?.color, baseColor),
    roughness: object.material?.roughness ?? 0.65,
    metalness: object.material?.metalness ?? 0.05
  });
  const mesh = new THREE.Mesh(meshGeometry, material);
  mesh.name = object.id;
  mesh.position.copy(zUpToThreePosition(object.transform?.position));
  mesh.rotation.copy(zUpRotationToThree(object.transform?.rotation));
  mesh.scale.set(...(object.transform?.scale || [1, 1, 1]));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function addTableDetails(scene, object) {
  if (object.kind !== 'table') return;

  const [sx = 1.4, sy = 0.7, sz = 0.12] = object.geometry?.size || [];
  const [x = 0, y = 0, z = 0.75] = object.transform?.position || [];
  const legHeight = Math.max(0.55, z - sz / 2);
  const legOffsetX = Math.max(0.2, sx / 2 - 0.12);
  const legOffsetY = Math.max(0.15, sy / 2 - 0.12);
  const legMaterial = new THREE.MeshStandardMaterial({
    color: 0x2d1f17,
    roughness: 0.55,
    metalness: 0.15
  });

  [
    [legOffsetX, legOffsetY],
    [-legOffsetX, legOffsetY],
    [legOffsetX, -legOffsetY],
    [-legOffsetX, -legOffsetY]
  ].forEach(([dx, dy]) => {
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.08, legHeight, 0.08), legMaterial);
    leg.name = `${object.id}_leg`;
    leg.position.copy(zUpToThreePosition([x + dx, y + dy, legHeight / 2]));
    leg.castShadow = true;
    leg.receiveShadow = true;
    scene.add(leg);
  });
}

function sceneSpecToRenderConfig(sceneSpec) {
  if (!sceneSpec) return null;

  const floorObject = sceneSpec.objects?.find(object => object.kind === 'floor');
  const [floorWidth = 8, floorDepth = 6] = floorObject?.geometry?.size || [];
  const walls = (sceneSpec.objects || [])
    .filter(object => object.kind === 'wall')
    .map(object => {
      const [sizeX = 4, sizeY = 0.2, sizeZ = 3] = object.geometry?.size || [];
      const rotationZ = object.transform?.rotation?.[2] || 0;
      const verticalWall = sizeX < sizeY && rotationZ === 0;
      return {
        id: object.id,
        position: object.transform?.position || [0, 0, sizeZ / 2],
        width: verticalWall ? sizeY : sizeX,
        height: sizeZ,
        thickness: verticalWall ? sizeX : sizeY,
        rotation: verticalWall ? 90 : rotationZ
      };
    });
  const shots = (sceneSpec.cameras || []).map(camera => ({
    shot_id: camera.id,
    focal_length_mm: camera.focal_length_mm || 35,
    start_position: camera.transform?.position || [0, -3, 1.5],
    end_position: camera.look_at || [0, 0, 1.2],
    duration_seconds: camera.duration_seconds || 5
  }));

  return {
    floor: { width: floorWidth, depth: floorDepth },
    walls,
    shots
  };
}

function getRenderConfig(sceneConfig, sceneSpec) {
  return sceneConfig || sceneSpecToRenderConfig(sceneSpec);
}

export default function ThreeCanvas({ sceneConfig, sceneSpec }) {
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

  // Update Meshes & Camera Path whenever sceneConfig or sceneSpec changes
  useEffect(() => {
    const scene = sceneRef.current;
    const renderConfig = getRenderConfig(sceneConfig, sceneSpec);
    if (!scene || !renderConfig) return;

    // Clear dynamic meshes
    const toRemove = [];
    scene.children.forEach(child => {
      if (child.type === 'Mesh' || child.type === 'Group' || child.type === 'Line' || child.type === 'GridHelper') {
        toRemove.push(child);
      }
    });
    toRemove.forEach(obj => scene.remove(obj));

    const { floor, walls, shots } = renderConfig;

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
      walls.forEach((wall) => {
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

    // 3. Render agent-authored props from the richer SceneSpec.
    if (sceneSpec?.objects?.length > 0) {
      sceneSpec.objects
        .filter(object => !['floor', 'wall', 'ceiling'].includes(object.kind))
        .forEach(object => {
          const objectNode = createSceneObjectMesh(object);
          scene.add(objectNode);
          addTableDetails(scene, object);
        });
    }

    // 4. Render Camera Path & Shot Frustum
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
  }, [sceneConfig, sceneSpec, activeShotIndex]);

  // Camera Animation Loop
  useEffect(() => {
    const renderConfig = getRenderConfig(sceneConfig, sceneSpec);
    if (!isPlaying || !renderConfig?.shots || renderConfig.shots.length === 0) return;

    const shot = renderConfig.shots[activeShotIndex] || renderConfig.shots[0];
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
  }, [isPlaying, sceneConfig, sceneSpec, activeShotIndex]);

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
        {getRenderConfig(sceneConfig, sceneSpec)?.shots?.length > 0 && (
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
              {getRenderConfig(sceneConfig, sceneSpec).shots.map((shot, idx) => (
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
