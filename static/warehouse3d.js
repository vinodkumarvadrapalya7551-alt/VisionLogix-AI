import * as THREE from "./vendor/build/three.module.js";
import { OrbitControls } from "./vendor/examples/jsm/controls/OrbitControls.js";

const container = document.querySelector("#warehouse-scene");
const zoneColors = { "1": 0x55b98a, "2": 0x5d9bd1, "3": 0xd65353 };
const robotMeshes = new Map();
const dynamicObstacleMeshes = new Map();
let renderer;
let scene;
let camera;
let controls;
let gridSize = { width: 24, height: 16 };
let routeGroup;
let warehouseFloorInitialized = false;
let movementStepSeconds = 0.12;
let fallbackCanvas;
let fallbackContext;
let fallbackResizeObserver;
let fallbackYaw = Math.PI / 4;
let fallbackPointerX = null;

function drawWarehouseFallback(state) {
  if (!fallbackContext || !fallbackCanvas) return;

  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, container.clientWidth);
  const height = Math.max(1, container.clientHeight);
  fallbackCanvas.width = Math.round(width * pixelRatio);
  fallbackCanvas.height = Math.round(height * pixelRatio);
  fallbackContext.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

  const context = fallbackContext;
  const grid = state.grid;
  const cosYaw = Math.cos(fallbackYaw);
  const sinYaw = Math.sin(fallbackYaw);
  const maxElevation = 2.1;
  const verticalScale = 0.52;
  const corners = [
    [0, 0],
    [grid.width, 0],
    [0, grid.height],
    [grid.width, grid.height],
  ].map(([x, z]) => [
    cosYaw * x - sinYaw * z,
    (sinYaw * x + cosYaw * z) * 0.52,
  ]);
  const minX = Math.min(...corners.map(([x]) => x));
  const maxX = Math.max(...corners.map(([x]) => x));
  const minY = Math.min(...corners.map(([, y]) => y));
  const maxY = Math.max(...corners.map(([, y]) => y));
  const scale = Math.max(
    1,
    Math.min(
      (width - 64) / (maxX - minX),
      (height - 86) / (maxY - minY + maxElevation * verticalScale),
    ),
  );
  const originX = (width - (maxX - minX) * scale) / 2;
  const originY = (height - (maxY - minY + maxElevation * verticalScale) * scale) / 2;
  const project = (x, z, elevation = 0) => [
    originX + (cosYaw * x - sinYaw * z - minX) * scale,
    originY +
      ((sinYaw * x + cosYaw * z) * 0.52 - minY + maxElevation * verticalScale) * scale -
      elevation * verticalScale * scale,
  ];
  const drawPolygon = (points, fill, stroke = null) => {
    context.beginPath();
    points.forEach(([x, z, elevation = 0], index) => {
      const [screenX, screenY] = project(x, z, elevation);
      if (index === 0) context.moveTo(screenX, screenY);
      else context.lineTo(screenX, screenY);
    });
    context.closePath();
    context.fillStyle = fill;
    context.fill();
    if (stroke) {
      context.strokeStyle = stroke;
      context.lineWidth = 1;
      context.stroke();
    }
  };
  const cellCenter = ([x, z], elevation = 0) =>
    project(x + 0.5, z + 0.5, elevation);
  const drawBox = (x, z, boxHeight, top, xFace, zFace, inset = 0) => {
    const startX = x + inset;
    const startZ = z + inset;
    const endX = x + 1 - inset;
    const endZ = z + 1 - inset;
    const edge = "rgba(7, 13, 16, 0.7)";
    drawPolygon(
      [
        [endX, startZ],
        [endX, endZ],
        [endX, endZ, boxHeight],
        [endX, startZ, boxHeight],
      ],
      xFace,
      edge,
    );
    drawPolygon(
      [
        [startX, endZ],
        [endX, endZ],
        [endX, endZ, boxHeight],
        [startX, endZ, boxHeight],
      ],
      zFace,
      edge,
    );
    drawPolygon(
      [
        [startX, startZ, boxHeight],
        [endX, startZ, boxHeight],
        [endX, endZ, boxHeight],
        [startX, endZ, boxHeight],
      ],
      top,
      edge,
    );
  };

  context.clearRect(0, 0, width, height);
  context.fillStyle = "#0d151b";
  context.fillRect(0, 0, width, height);
  drawPolygon(
    [[0, 0], [grid.width, 0], [grid.width, grid.height], [0, grid.height]],
    "#19242b",
    "#52636a",
  );

  context.strokeStyle = "rgba(132, 157, 151, 0.2)";
  context.lineWidth = 1;
  for (let x = 0; x <= grid.width; x += 1) {
    const [startX, startY] = project(x, 0);
    const [endX, endY] = project(x, grid.height);
    context.beginPath();
    context.moveTo(startX, startY);
    context.lineTo(endX, endY);
    context.stroke();
  }
  for (let z = 0; z <= grid.height; z += 1) {
    const [startX, startY] = project(0, z);
    const [endX, endY] = project(grid.width, z);
    context.beginPath();
    context.moveTo(startX, startY);
    context.lineTo(endX, endY);
    context.stroke();
  }

  for (const zone of state.zones ?? []) {
    const [x, z] = zone.target;
    drawPolygon(
      [[x, z], [x + 1, z], [x + 1, z + 1], [x, z + 1]],
      `${zone.color}78`,
      zone.color,
    );
    const [labelX, labelY] = cellCenter(zone.target, 0.06);
    context.fillStyle = "#e8f0e8";
    context.font = `600 ${Math.max(9, Math.min(12, scale * 0.28))}px Segoe UI, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(zone.name, labelX, labelY);
  }

  for (const robot of state.robots ?? []) {
    const route = robot.route ?? [];
    if (route.length > 1 && robot.status !== "delivered" && robot.status !== "blocked") {
      context.beginPath();
      route.forEach((point, index) => {
        const [x, y] = cellCenter(point, 0.035);
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      context.strokeStyle =
        `#${(zoneColors[robot.zone_id] ?? 0xffffff).toString(16).padStart(6, "0")}`;
      context.globalAlpha = 0.5;
      context.lineWidth = Math.max(1.5, scale * 0.08);
      context.stroke();
      context.globalAlpha = 1;
    }
  }

  const obstacles = [
    ...(state.static_obstacles ?? grid.obstacles).map(([x, z]) => [x, z, false]),
    ...(state.dynamic_obstacles ?? []).map(([x, z]) => [x, z, true]),
  ].sort((first, second) => {
    const firstDepth = (first[0] + first[1]) * sinYaw;
    const secondDepth = (second[0] + second[1]) * sinYaw;
    return firstDepth - secondDepth;
  });
  for (const [x, z, dynamic] of obstacles) {
    drawBox(
      x,
      z,
      dynamic ? 0.78 : 1.5,
      dynamic ? "#f07b69" : "#9aa9ad",
      dynamic ? "#873c34" : "#3f4e57",
      dynamic ? "#b54f43" : "#56646b",
      0.06,
    );
  }

  const robots = [...(state.robots ?? [])]
    .filter((robot) => robot.position && robot.status !== "queued")
    .sort(
      (first, second) =>
        (first.position[0] + first.position[1] -
          second.position[0] - second.position[1]) * sinYaw,
    );
  for (const robot of robots) {
    const route = robot.route ?? [];
    let [x, z] = robot.position;
    const next = route[(robot.route_index ?? 0) + 1];
    if (robot.status === "moving" && next) {
      const progress = Math.min(1, Math.max(0, robot.step_progress ?? 0));
      x += (next[0] - x) * progress;
      z += (next[1] - z) * progress;
    }
    const color = robot.status === "blocked"
      ? "#f08b7c"
      : robot.status === "delivered"
        ? "#5d9bd1"
        : "#c5f477";
    drawBox(
      x + 0.16,
      z + 0.16,
      0.4,
      color,
      "#35443d",
      "#71823e",
      0,
    );
    const [labelX, labelY] = cellCenter([x, z], 0.68);
    context.fillStyle = "#edf1eb";
    context.font = `bold ${Math.max(8, Math.min(11, scale * 0.25))}px Segoe UI, sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(`ID ${robot.marker_id}`, labelX, labelY);
  }

  context.fillStyle = "#9aa99f";
  context.font = "10px Segoe UI, sans-serif";
  context.textAlign = "left";
  context.textBaseline = "bottom";
  context.fillText("DRAG TO ORBIT · ISOMETRIC 3D VIEW (WEBGL-FREE)", 12, height - 10);
}

function startCanvasFallback(error) {
  try {
    fallbackCanvas = document.createElement("canvas");
    fallbackCanvas.setAttribute(
      "aria-label",
      "Orbitable isometric warehouse view showing elevated shelves, delivery zones, routes, and robots",
    );
    fallbackCanvas.style.touchAction = "none";
    fallbackContext = fallbackCanvas.getContext("2d");
    if (!fallbackContext) throw new Error("The browser could not create a 2D canvas context.");

    container.replaceChildren(fallbackCanvas);
    container.setAttribute("role", "application");
    window.updateWarehouseScene = updateWarehouseScene;
    window.warehouseRendererFallback = true;
    const initialState = window.initialWarehouseState;
    if (initialState) drawWarehouseFallback(initialState);

    fallbackResizeObserver = new ResizeObserver(() => {
      const state = window.initialWarehouseState;
      if (state) drawWarehouseFallback(state);
    });
    fallbackResizeObserver.observe(container);
    document.querySelector("#warehouse-message").textContent =
      "ISOMETRIC 3D VIEW · WEBGL UNAVAILABLE";
    fallbackCanvas.addEventListener("pointerdown", (event) => {
      fallbackPointerX = event.clientX;
      fallbackCanvas.setPointerCapture(event.pointerId);
    });
    fallbackCanvas.addEventListener("pointermove", (event) => {
      if (fallbackPointerX === null) return;
      fallbackYaw += (event.clientX - fallbackPointerX) * 0.008;
      fallbackPointerX = event.clientX;
      const currentState = window.initialWarehouseState;
      if (currentState) drawWarehouseFallback(currentState);
    });
    const stopOrbit = () => {
      fallbackPointerX = null;
    };
    fallbackCanvas.addEventListener("pointerup", stopOrbit);
    fallbackCanvas.addEventListener("pointercancel", stopOrbit);
    console.warn("WebGL unavailable; using orbitable isometric warehouse rendering.", error);
  } catch (fallbackError) {
    container.textContent =
      `Warehouse visualization unavailable: ${fallbackError.message}`;
    container.setAttribute("role", "alert");
    document.querySelector("#warehouse-message").textContent =
      "WAREHOUSE VISUALIZATION UNAVAILABLE";
    console.error("Warehouse 2D fallback could not be initialized.", fallbackError);
  }
}

function worldPosition([x, z], y = 0) {
  return new THREE.Vector3(
    x - gridSize.width / 2 + 0.5,
    y,
    z - gridSize.height / 2 + 0.5,
  );
}

function makeLabel(text, color) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 96;
  const context = canvas.getContext("2d");
  context.fillStyle = "#0c141bd9";
  context.beginPath();
  context.roundRect(5, 5, 246, 86, 14);
  context.fill();
  context.fillStyle = color;
  context.font = "bold 34px Segoe UI, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 128, 48);

  const texture = new THREE.CanvasTexture(canvas);
  const label = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }),
  );
  label.scale.set(1.35, 0.5, 1);
  return label;
}

function addWarehouseFloor(state) {
  gridSize = state.grid;
  const width = gridSize.width;
  const height = gridSize.height;
  const floor = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.2, height),
    new THREE.MeshStandardMaterial({ color: 0x19242b, roughness: 0.92 }),
  );
  floor.position.y = -0.16;
  floor.receiveShadow = true;
  scene.add(floor);

  const gridPoints = [];
  for (let x = 0; x <= width; x += 1) {
    gridPoints.push(
      new THREE.Vector3(x - width / 2, -0.05, -height / 2),
      new THREE.Vector3(x - width / 2, -0.05, height / 2),
    );
  }
  for (let z = 0; z <= height; z += 1) {
    gridPoints.push(
      new THREE.Vector3(-width / 2, -0.05, z - height / 2),
      new THREE.Vector3(width / 2, -0.05, z - height / 2),
    );
  }
  const gridGeometry = new THREE.BufferGeometry().setFromPoints(gridPoints);
  scene.add(
    new THREE.LineSegments(
      gridGeometry,
      new THREE.LineBasicMaterial({ color: 0x30404a, transparent: true, opacity: 0.55 }),
    ),
  );

  for (const [x, z] of state.static_obstacles ?? state.grid.obstacles) {
    const shelf = new THREE.Mesh(
      new THREE.BoxGeometry(0.84, 1.45, 0.84),
      new THREE.MeshStandardMaterial({
        color: 0x56636b,
        roughness: 0.7,
        metalness: 0.22,
      }),
    );
    shelf.position.copy(worldPosition([x, z], 0.68));
    shelf.castShadow = true;
    shelf.receiveShadow = true;
    scene.add(shelf);

    const shelfTop = new THREE.Mesh(
      new THREE.BoxGeometry(0.86, 0.07, 0.86),
      new THREE.MeshStandardMaterial({ color: 0x839198, metalness: 0.25 }),
    );
    shelfTop.position.copy(worldPosition([x, z], 1.42));
    shelfTop.castShadow = true;
    scene.add(shelfTop);
  }

  for (const zone of state.zones) {
    const color = zoneColors[zone.id];
    const marker = new THREE.Mesh(
      new THREE.BoxGeometry(1.7, 0.04, 1.7),
      new THREE.MeshStandardMaterial({
        color,
        transparent: true,
        opacity: 0.36,
        emissive: color,
        emissiveIntensity: 0.12,
      }),
    );
    marker.position.copy(worldPosition(zone.target, 0.015));
    scene.add(marker);

    const label = makeLabel(
      `${zone.name.toUpperCase()} · ${zone.first_marker_id}-${zone.last_marker_id}`,
      `#${zoneColors[zone.id].toString(16).padStart(6, "0")}`,
    );
    label.position.copy(worldPosition(zone.target, 0.6));
    scene.add(label);
  }

  const entry = makeLabel("ROBOT ENTRY", "#ecf2f4");
  entry.scale.set(1.1, 0.42, 1);
  entry.position.set(-width / 2 + 1.4, 0.35, 0);
  scene.add(entry);
}

function updateDynamicObstacles(state) {
  const current = new Set();
  for (const [x, z] of state.dynamic_obstacles ?? []) {
    const key = `${x},${z}`;
    current.add(key);
    if (dynamicObstacleMeshes.has(key)) continue;

    const obstacle = new THREE.Mesh(
      new THREE.BoxGeometry(0.84, 0.95, 0.84),
      new THREE.MeshStandardMaterial({
        color: 0xc85b4b,
        emissive: 0x5c1c17,
        emissiveIntensity: 0.5,
        roughness: 0.75,
      }),
    );
    obstacle.position.copy(worldPosition([x, z], 0.43));
    obstacle.castShadow = true;
    obstacle.userData.dynamicObstacle = true;
    scene.add(obstacle);
    dynamicObstacleMeshes.set(key, obstacle);
  }

  for (const [key, obstacle] of dynamicObstacleMeshes) {
    if (current.has(key)) continue;
    scene.remove(obstacle);
    obstacle.geometry.dispose();
    obstacle.material.dispose();
    dynamicObstacleMeshes.delete(key);
  }
}

function createRobot(robot) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.62, 0.4, 0.72),
    new THREE.MeshStandardMaterial({
      color: zoneColors[robot.zone_id] ?? 0xffffff,
      roughness: 0.45,
      metalness: 0.2,
      emissive: zoneColors[robot.zone_id] ?? 0xffffff,
      emissiveIntensity: 0.1,
    }),
  );
  body.castShadow = true;
  group.add(body);

  const cargo = new THREE.Mesh(
    new THREE.BoxGeometry(0.34, 0.3, 0.36),
    new THREE.MeshStandardMaterial({
      color: 0xc99358,
      roughness: 0.75,
    }),
  );
  cargo.position.set(0, 0.36, -0.18);
  cargo.castShadow = true;
  group.add(cargo);

  const top = new THREE.Mesh(
    new THREE.CylinderGeometry(0.14, 0.14, 0.12, 20),
    new THREE.MeshStandardMaterial({ color: 0xeaf2f5, metalness: 0.25 }),
  );
  top.position.y = 0.25;
  group.add(top);

  const label = makeLabel(`ID ${robot.robot_id}`, "#ecf2f4");
  label.position.y = 0.78;
  group.add(label);
  scene.add(group);

  return {
    group,
    cargo,
    routeKey: "",
    routeLine: null,
    route: [],
    displayProgress: 0,
    backendProgress: 0,
    lastAnimationAt: performance.now(),
    status: robot.status,
  };
}

function updateRoute(robot, robotScene) {
  const routeKey = JSON.stringify(robot.route);
  if (robotScene.routeKey === routeKey) return;
  if (robotScene.routeLine) {
    routeGroup.remove(robotScene.routeLine);
    robotScene.routeLine.geometry.dispose();
    robotScene.routeLine.material.dispose();
  }

  robotScene.routeKey = routeKey;
  const points = robot.route.map((point) => worldPosition(point, 0.08));
  if (points.length < 2) return;
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  robotScene.routeLine = new THREE.Line(
    geometry,
    new THREE.LineBasicMaterial({
      color: zoneColors[robot.zone_id] ?? 0xffffff,
      transparent: true,
      opacity: robot.status === "delivered" ? 0.2 : 0.78,
    }),
  );
  routeGroup.add(robotScene.routeLine);
}

function updateWarehouseScene(state) {
  if (fallbackContext) {
    drawWarehouseFallback(state);
    return;
  }
  if (!scene) return;
  movementStepSeconds = state.step_seconds ?? movementStepSeconds;
  updateDynamicObstacles(state);
  for (const robot of state.robots) {
    let robotScene = robotMeshes.get(robot.robot_id);
    if (!robotScene) {
      robotScene = createRobot(robot);
      robotMeshes.set(robot.robot_id, robotScene);
    }
    const routeChanged = robotScene.routeKey !== JSON.stringify(robot.route);
    updateRoute(robot, robotScene);
    robotScene.route = robot.route;
    const lastIndex = Math.max(0, robot.route.length - 1);
    const routeProgress = Math.min(
      lastIndex,
      Math.max(0, robot.route_index + (robot.step_progress ?? 0)),
    );
    robotScene.backendProgress = routeProgress;
    if (routeChanged) {
      robotScene.displayProgress = routeProgress;
      robotScene.lastAnimationAt = performance.now();
      if (robot.position) {
        robotScene.group.position.copy(worldPosition(robot.position, 0.28));
      }
    }
    robotScene.status = robot.status;
    robotScene.group.userData.status = robot.status;
    robotScene.cargo.visible = robot.status !== "delivered";
    robotScene.group.visible =
      robot.position !== null &&
      robot.status !== "queued" &&
      !(robot.status === "delivered" && robotScene.displayProgress >= lastIndex);
  }

  for (const [robotId, robotScene] of robotMeshes) {
    if (state.robots.some((robot) => robot.robot_id === robotId)) continue;
    scene.remove(robotScene.group);
    if (robotScene.routeLine) {
      routeGroup.remove(robotScene.routeLine);
      robotScene.routeLine.geometry.dispose();
      robotScene.routeLine.material.dispose();
    }
    robotScene.group.traverse((object) => {
      object.geometry?.dispose();
      const materials = Array.isArray(object.material)
        ? object.material
        : object.material
          ? [object.material]
          : [];
      for (const material of materials) {
        material.map?.dispose();
        material.dispose();
      }
    });
    robotMeshes.delete(robotId);
  }
}

function robotWorldPosition(robotScene) {
  if (robotScene.route.length === 0) return null;
  const lastIndex = robotScene.route.length - 1;
  const progress = Math.min(lastIndex, Math.max(0, robotScene.displayProgress));
  const index = Math.floor(progress);
  const fraction = progress - index;
  if (index === lastIndex) {
    return worldPosition(robotScene.route[lastIndex], 0.28);
  }

  const [fromX, fromZ] = robotScene.route[index];
  const [toX, toZ] = robotScene.route[index + 1];
  return worldPosition(
    [fromX + (toX - fromX) * fraction, fromZ + (toZ - fromZ) * fraction],
    0.28,
  );
}

function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  for (const robotScene of robotMeshes.values()) {
    const elapsedSeconds = Math.max(0, (now - robotScene.lastAnimationAt) / 1000);
    robotScene.lastAnimationAt = now;
    if (robotScene.status === "moving" || robotScene.status === "delivered") {
      const remaining = robotScene.backendProgress - robotScene.displayProgress;
      const maxAdvance = elapsedSeconds / movementStepSeconds;
      robotScene.displayProgress += Math.min(remaining, maxAdvance);
    }
    const position = robotWorldPosition(robotScene);
    if (position) robotScene.group.position.copy(position);
    const lastIndex = Math.max(0, robotScene.route.length - 1);
    if (robotScene.status === "delivered" && robotScene.displayProgress >= lastIndex) {
      robotScene.group.visible = false;
    }
    if (robotScene.group.userData.status === "moving") {
      robotScene.group.rotation.y += 0.012;
    }
  }
  controls.update();
  renderer.render(scene, camera);
}

function startScene() {
  if (!container) return;
  try {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0d151b);
    scene.fog = new THREE.Fog(0x0d151b, 24, 48);

    camera = new THREE.PerspectiveCamera(43, 1, 0.1, 100);
    camera.position.set(16, 21, 22);
    camera.lookAt(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.replaceChildren(renderer.domElement);
    container.append(renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enableDamping = true;
    controls.minDistance = 15;
    controls.maxDistance = 42;
    controls.maxPolarAngle = Math.PI / 2.05;

    scene.add(new THREE.HemisphereLight(0xb8d0dc, 0x202a30, 2.2));
    const keyLight = new THREE.DirectionalLight(0xfff0d5, 3);
    keyLight.position.set(-7, 16, 8);
    keyLight.castShadow = true;
    scene.add(keyLight);
    scene.add(new THREE.AmbientLight(0x91a9b5, 0.55));

    routeGroup = new THREE.Group();
    scene.add(routeGroup);
    const warehouse = window.initialWarehouseState;
    if (warehouse) {
      addWarehouseFloor(warehouse);
      warehouseFloorInitialized = true;
    }

    const resize = new ResizeObserver(() => {
      const width = Math.max(1, container.clientWidth);
      const height = Math.max(1, container.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    });
    resize.observe(container);
    window.updateWarehouseScene = updateWarehouseScene;
    if (warehouse) updateWarehouseScene(warehouse);
    animate();
  } catch (error) {
    startCanvasFallback(error);
  }
}

async function loadWarehouse() {
  try {
    const response = await fetch("/api/warehouse", { cache: "no-store" });
    if (!response.ok) throw new Error("Warehouse API returned an error.");
    const state = await response.json();
    window.initialWarehouseState = state;
    if (scene || fallbackContext) {
      if (!warehouseFloorInitialized) {
        if (scene) addWarehouseFloor(state);
        warehouseFloorInitialized = true;
      }
      updateWarehouseScene(state);
    }
  } catch (error) {
    container.textContent = `Warehouse data unavailable: ${error.message}`;
  }
}

startScene();
loadWarehouse();
