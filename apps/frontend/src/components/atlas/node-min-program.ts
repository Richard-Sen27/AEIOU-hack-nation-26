/**
 * Sigma's circle program with a zoom-dependent floor on the on-screen radius,
 * so leaf dots become easy to see, hover and click once the camera is zoomed
 * in, while the overview and larger dots are drawn exactly as before. The hit
 * area (picking pass) gets a few extra pixels on top.
 *
 * Browser only (Sigma touches WebGL globals at import time).
 */
import { NodeCircleProgram } from "sigma/rendering";
import type { RenderParams } from "sigma/types";

import { nodeHitPadding, nodeMinRadius } from "./atlas-model";

const VERTEX = /* glsl */ `
attribute vec4 a_id;
attribute vec4 a_color;
attribute vec2 a_position;
attribute float a_size;
attribute float a_angle;

uniform mat3 u_matrix;
uniform float u_sizeRatio;
uniform float u_correctionRatio;
uniform float u_minRadius;
uniform float u_hitPadding;

varying vec4 v_color;
varying vec2 v_diffVector;
varying float v_radius;
varying float v_border;

const float bias = 255.0 / 254.0;

void main() {
  // Radius in screen pixels: Sigma's scaled size, but never below the floor.
  float px = max(a_size / u_sizeRatio, u_minRadius);
  #ifdef PICKING_MODE
  px += u_hitPadding;
  #endif
  float size = px * u_correctionRatio * 4.0;
  vec2 diffVector = size * vec2(cos(a_angle), sin(a_angle));
  vec2 position = a_position + diffVector;
  gl_Position = vec4((u_matrix * vec3(position, 1)).xy, 0, 1);
  v_diffVector = diffVector;
  v_radius = size / 2.0;
  #ifdef PICKING_MODE
  v_color = a_id;
  #else
  v_color = a_color;
  #endif
  v_color.a *= bias;
}
`;

const UNIFORMS = ["u_sizeRatio", "u_correctionRatio", "u_matrix", "u_minRadius", "u_hitPadding"] as const;

export class NodeMinCircleProgram extends NodeCircleProgram {
  getDefinition() {
    const def = super.getDefinition();
    return { ...def, VERTEX_SHADER_SOURCE: VERTEX, UNIFORMS: UNIFORMS as unknown as typeof def.UNIFORMS };
  }

  setUniforms(params: RenderParams, info: Parameters<NodeCircleProgram["setUniforms"]>[1]) {
    super.setUniforms(params, info);
    const { gl, uniformLocations } = info;
    const loc = uniformLocations as Record<string, WebGLUniformLocation>;
    gl.uniform1f(loc.u_minRadius, nodeMinRadius(params.zoomRatio));
    gl.uniform1f(loc.u_hitPadding, nodeHitPadding(params.zoomRatio));
  }
}
