import * as THREE from "./vendor/build/three.module.js";
import { OrbitControls } from "./vendor/examples/jsm/controls/OrbitControls.js";

const container = document.querySelector("#warehouse-scene");
const zoneColors = { "1": 0x55b98a, "2": 0x5d9bd1, "3": 0xd65353 };
const robotMeshes = new Map();
let renderer;
let scene;
let camera;
let controls;
let gridSize = { width: 24, height: 16 };
let routeGroup;

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

  for (const [x, z] of state.grid.obstacles) {
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
    target: new THREE.Vector3(),
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
  if (!scene) return;
  for (const robot of state.robots) {
    let robotScene = robotMeshes.get(robot.robot_id);
    if (!robotScene) {
      robotScene = createRobot(robot);
      robotMeshes.set(robot.robot_id, robotScene);
    }
    updateRoute(robot, robotScene);
    if (robot.position) {
      robotScene.target.copy(worldPosition(robot.position, 0.28));
    }
    robotScene.group.userData.status = robot.status;
    robotScene.cargo.visible = robot.status !== "delivered";
    robotScene.group.visible = robot.position !== null;
  }

  for (const [robotId, robotScene] of robotMeshes) {
    if (state.robots.some((robot) => robot.robot_id === robotId)) continue;
    scene.remove(robotScene.group);
    if (robotScene.routeLine) {
      routeGroup.remove(robotScene.routeLine);
      robotScene.routeLine.geometry.dispose();
      robotScene.routeLine.material.dispose();
    }
    robotMeshes.delete(robotId);
  }
}

function animate() {
  requestAnimationFrame(animate);
  for (const robotScene of robotMeshes.values()) {
    robotScene.group.position.lerp(robotScene.target, 0.13);
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
    if (warehouse) addWarehouseFloor(warehouse);
    else {
      const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(24, 16),
        new THREE.MeshStandardMaterial({ color: 0x19242b }),
      );
      floor.rotation.x = -Math.PI / 2;
      floor.position.y = -0.1;
      scene.add(floor);
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
    container.textContent = `3D warehouse could not be initialized: ${error.message}`;
    container.setAttribute("role", "alert");
    document.querySelector("#warehouse-message").textContent =
      "3D RENDERER ERROR · CHECK WEBGL SUPPORT";
  }
}

async function loadWarehouse() {
  try {
    const response = await fetch("/api/warehouse", { cache: "no-store" });
    if (!response.ok) throw new Error("Warehouse API returned an error.");
    const state = await response.json();
    window.initialWarehouseState = state;
    if (scene) {
      addWarehouseFloor(state);
      updateWarehouseScene(state);
    }
  } catch (error) {
    container.textContent = `Warehouse data unavailable: ${error.message}`;
  }
}

startScene();
loadWarehouse();
