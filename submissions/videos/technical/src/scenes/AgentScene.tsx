import type React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {SceneFrame} from '../components/SceneFrame';
import {CLAIMS, SCENES, TOOLS} from '../content';
import {COLORS, MONO, RADIUS, SAFE, SHADOW} from '../theme';

const scene = SCENES.agent;
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);

// Narration timing (frames, scene-relative): "a LangGraph turn" 6-80,
// "OpenAI models" 80-120, "six graph tools" 120-166, "before anything is
// shown" 173-213, "deletes any claim citing an edge the tools never
// returned" 218-330.
const T = {
  nodesStart: 8,
  nodeStep: 12,
  openaiIn: 80,
  toolsIn: 112,
  returnedIn: 150,
  claimsIn: 175,
  gateOn: 205,
  move: [222, 256] as const,
  strike: 240,
  fall: [270, 300] as const,
};

type Box = {readonly id: string; readonly x: number; readonly w: number};

// Row of turn nodes. Presidio runs before the LangGraph run starts.
const ROW_Y = 220;
const ROW_H = 100;
const BOXES: readonly Box[] = [
  {id: 'Presidio', x: SAFE.left, w: 230},
  {id: 'safety', x: 432, w: 200},
  {id: 'entities', x: 692, w: 220},
  {id: 'agent', x: 972, w: 270},
  {id: 'postcheck', x: 1302, w: 250},
  {id: 'persist', x: 1612, w: 1778 - 1612},
];

const BOTTOM_Y = 640;
const CLAIM = {x: 700, w: 440, h: 72, gap: 18};
const GATE_X = 1208;
const REPLY_X = 1290;

export const AgentScene: React.FC = () => {
  const frame = useCurrentFrame();
  const gate = interpolate(frame, [T.gateOn, T.gateOn + 10], [0, 1], clamp);

  return (
    <SceneFrame scene={scene} codePath="api/services/chat · build_turn_graph">
      {/* LangGraph frame around the in-graph nodes. */}
      <div
        style={{
          position: 'absolute',
          left: BOXES[1].x - 24,
          top: ROW_Y - 64,
          width: 1778 - BOXES[1].x + 24,
          height: ROW_H + 88 + 220,
          borderRadius: RADIUS * 2,
          border: `2px dashed ${COLORS.border}`,
          opacity: interpolate(frame, [T.nodesStart, T.nodesStart + 12], [0, 1], clamp),
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 24,
            top: 12,
            fontFamily: MONO,
            fontSize: 26,
            color: COLORS.mutedForeground,
          }}
        >
          LangGraph StateGraph
        </div>
      </div>

      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        {/* Arrows between turn nodes. */}
        {BOXES.slice(0, -1).map((b, i) => {
          const next = BOXES[i + 1];
          const on = T.nodesStart + (i + 1) * T.nodeStep;
          return (
            <line
              key={b.id}
              x1={b.x + b.w + 6}
              y1={ROW_Y + ROW_H / 2}
              x2={next.x - 10}
              y2={ROW_Y + ROW_H / 2}
              stroke={COLORS.mutedForeground}
              strokeWidth={3}
              markerEnd="url(#arrow)"
              opacity={interpolate(frame, [on - 4, on + 4], [0, 1], clamp)}
            />
          );
        })}
        {/* Agent to its tools: a trunk and a bar over the tool rows. */}
        <g opacity={interpolate(frame, [T.toolsIn, T.toolsIn + 8], [0, 1], clamp)} stroke={COLORS.mutedForeground} strokeWidth={2} fill="none">
          <path
            d={`M ${BOXES[3].x + BOXES[3].w / 2} ${ROW_Y + ROW_H} V ${TOOL_BAR_Y} M ${toolPos(0).x + 150} ${TOOL_BAR_Y} H ${toolPos(2).x + 150}`}
          />
          {[0, 1, 2].map((i) => (
            <path key={i} d={`M ${toolPos(i).x + 150} ${TOOL_BAR_Y} V ${toolPos(i).y}`} />
          ))}
        </g>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill={COLORS.mutedForeground} />
          </marker>
        </defs>
      </svg>

      {/* Turn nodes. */}
      {BOXES.map((b, i) => {
        const on = T.nodesStart + i * T.nodeStep;
        const isAgent = b.id === 'agent';
        const isCheck = b.id === 'postcheck';
        return (
          <div
            key={b.id}
            style={{
              position: 'absolute',
              left: b.x,
              top: ROW_Y,
              width: b.w,
              height: ROW_H,
              boxSizing: 'border-box',
              borderRadius: RADIUS,
              backgroundColor: isCheck
                ? `color-mix(in oklch, ${COLORS.secondary} ${Math.round(gate * 100)}%, ${COLORS.card})`
                : b.id === 'Presidio'
                  ? COLORS.muted
                  : COLORS.card,
              color: isCheck && gate > 0.5 ? COLORS.secondaryForeground : COLORS.foreground,
              border: `2px solid ${isAgent ? COLORS.primary : COLORS.border}`,
              boxShadow: SHADOW,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              fontFamily: b.id === 'Presidio' ? undefined : MONO,
              fontSize: 32,
              fontWeight: 600,
              opacity: interpolate(frame, [on, on + 8], [0, 1], clamp),
              translate: interpolate(frame, [on, on + 14], ['0px 20px', '0px 0px'], {...clamp, easing: ease}),
            }}
          >
            {b.id}
            {isAgent ? (
              <span
                style={{
                  fontFamily: undefined,
                  fontSize: 22,
                  fontWeight: 600,
                  padding: '2px 12px',
                  borderRadius: 999,
                  backgroundColor: COLORS.foreground,
                  color: COLORS.card,
                  opacity: interpolate(frame, [T.openaiIn, T.openaiIn + 8], [0, 1], clamp),
                }}
              >
                OpenAI Responses
              </span>
            ) : null}
          </div>
        );
      })}

      {/* The six tools the model may call. */}
      {TOOLS.map((t, i) => {
        const pos = toolPos(i);
        const on = T.toolsIn + i * 4;
        return (
          <div
            key={t}
            style={{
              position: 'absolute',
              left: pos.x,
              top: pos.y,
              width: 300,
              height: 50,
              borderRadius: 10,
              backgroundColor: COLORS.card,
              border: `1px solid ${COLORS.border}`,
              fontFamily: MONO,
              fontSize: 24,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: interpolate(frame, [on, on + 8], [0, 1], clamp),
            }}
          >
            {t}
          </div>
        );
      })}

      {/* Edge ids the tools returned this turn (TurnState.edge_ids). */}
      <div
        style={{
          position: 'absolute',
          left: SAFE.left,
          top: BOTTOM_Y,
          width: 470,
          padding: '20px 24px',
          boxSizing: 'border-box',
          borderRadius: RADIUS * 1.5,
          backgroundColor: COLORS.card,
          border: `1px solid ${COLORS.border}`,
          boxShadow: SHADOW,
          opacity: interpolate(frame, [T.returnedIn, T.returnedIn + 10], [0, 1], clamp),
        }}
      >
        <div style={{fontFamily: MONO, fontSize: 24, color: COLORS.mutedForeground}}>state.edge_ids</div>
        {CLAIMS.filter((c) => c.kept).map((c) => (
          <div
            key={c.edge}
            style={{
              marginTop: 14,
              fontFamily: MONO,
              fontSize: 28,
              padding: '8px 16px',
              borderRadius: 10,
              border: `2px solid ${COLORS.secondary}`,
              color: COLORS.foreground,
            }}
          >
            {c.edge}
          </div>
        ))}
      </div>

      {/* The gate. */}
      <div
        style={{
          position: 'absolute',
          left: GATE_X - 3,
          top: BOTTOM_Y - 10,
          width: 6,
          height: 3 * (CLAIM.h + CLAIM.gap) + 2,
          borderRadius: 3,
          backgroundColor: COLORS.secondary,
          opacity: gate,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: GATE_X,
          top: BOTTOM_Y - 52,
          translate: '-50% 0',
          fontFamily: MONO,
          fontSize: 24,
          color: COLORS.secondary,
          whiteSpace: 'nowrap',
          opacity: gate,
        }}
      >
        edge_ids ⊆ state.edge_ids
      </div>

      {/* The reply side. */}
      <div
        style={{
          position: 'absolute',
          left: REPLY_X,
          top: BOTTOM_Y - 10,
          width: 1778 - REPLY_X,
          height: 2 * (CLAIM.h + CLAIM.gap) + 2,
          borderRadius: RADIUS * 1.5,
          border: `2px solid ${COLORS.border}`,
          backgroundColor: `color-mix(in oklch, ${COLORS.card} 60%, transparent)`,
          opacity: gate,
        }}
      />

      {/* Claims from the draft answer. */}
      {CLAIMS.map((c, i) => {
        const start = T.claimsIn + i * 5;
        const move = interpolate(frame, T.move, [0, 1], {...clamp, easing: Easing.inOut(Easing.cubic)});
        const keptRow = CLAIMS.filter((x, j) => x.kept && j < i).length;
        const fall = interpolate(frame, T.fall, [0, 1], {...clamp, easing: Easing.in(Easing.quad)});
        const struck = interpolate(frame, [T.strike, T.strike + 10], [0, 1], clamp);
        const x = c.kept ? CLAIM.x + (REPLY_X + 24 - CLAIM.x) * move : CLAIM.x + (GATE_X - CLAIM.w - 20 - CLAIM.x) * move;
        const y = c.kept ? BOTTOM_Y + i * (CLAIM.h + CLAIM.gap) + (keptRow - i) * (CLAIM.h + CLAIM.gap) * move : BOTTOM_Y + i * (CLAIM.h + CLAIM.gap);
        return (
          <div
            key={c.edge}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              width: CLAIM.w,
              height: CLAIM.h,
              boxSizing: 'border-box',
              borderRadius: RADIUS,
              backgroundColor: COLORS.card,
              border: `2px solid ${c.kept ? COLORS.border : `color-mix(in oklch, ${COLORS.destructive} ${Math.round(struck * 100)}%, ${COLORS.border})`}`,
              boxShadow: SHADOW,
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              padding: '0 20px',
              fontFamily: MONO,
              fontSize: 26,
              opacity: interpolate(frame, [start, start + 8], [0, 1], clamp) * (c.kept ? 1 : 1 - fall),
              translate: c.kept ? '0px 0px' : `0px ${fall * 120}px`,
              rotate: c.kept ? '0deg' : `${fall * 6}deg`,
            }}
          >
            <span style={{color: COLORS.mutedForeground}}>draft</span>
            <span
              style={{
                position: 'relative',
                color: c.kept ? COLORS.foreground : COLORS.destructive,
              }}
            >
              {c.edge}
              {c.kept ? null : (
                <span
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: '52%',
                    height: 4,
                    width: `${struck * 100}%`,
                    backgroundColor: COLORS.destructive,
                  }}
                />
              )}
            </span>
            <span
              style={{
                marginLeft: 'auto',
                fontWeight: 700,
                color: c.kept ? COLORS.secondary : COLORS.destructive,
                opacity: c.kept ? interpolate(frame, [T.move[1] - 6, T.move[1]], [0, 1], clamp) : struck,
              }}
            >
              {c.kept ? '✓' : '✗'}
            </span>
          </div>
        );
      })}
    </SceneFrame>
  );
};

// Two rows of three tool chips under the agent.
const TOOL_BAR_Y = 372;
function toolPos(i: number) {
  const col = i % 3;
  const row = Math.floor(i / 3);
  return {x: 700 + col * 320, y: 400 + row * 64};
}
