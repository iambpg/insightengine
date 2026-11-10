// One chassis is always drawn at this pixel height. A wider switch scrolls sideways.
export const FACEPLATE_HEIGHT = 168;

/** Catalyst 9200L-48P front. Switches, FortiGates and FortiSwitches share this frame. */
const CHASSIS_NATIVE = { width: 2284, height: 217 };
export const CHASSIS_WIDTH = Math.round(FACEPLATE_HEIGHT * (CHASSIS_NATIVE.width / CHASSIS_NATIVE.height));
export const CHASSIS_PAD = 8;
export const CHASSIS_INNER_H = 96;

export function lockedChassis(pad = CHASSIS_PAD, innerH = CHASSIS_INNER_H) {
  const vbH = innerH + pad * 2;
  const vbW = vbH * (CHASSIS_WIDTH / FACEPLATE_HEIGHT);
  return { vbW, vbH, innerW: vbW - pad * 2, innerH, pad };
}
