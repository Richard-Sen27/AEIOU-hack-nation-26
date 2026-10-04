import React from 'react';
import {AbsoluteFill, Series, useVideoConfig} from 'remotion';
import {ArriveScene} from './scenes/ArriveScene';
import {CloseScene} from './scenes/CloseScene';
import {DrWuScene} from './scenes/DrWuScene';
import {GapScene} from './scenes/GapScene';
import {GraphScene} from './scenes/GraphScene';
import {PeopleScene} from './scenes/PeopleScene';
import {COLORS} from './theme';

// Hackathon rule: the submission must not exceed 60 seconds.
export const MAX_DURATION_IN_FRAMES = 1800;

// Fails the preview and any render when the scenes stop adding up: more than
// the 60 s cap, or a total that differs from the composition's duration
// (which would cut the end off or leave black frames).
const TimelineCheck: React.FC<{
  readonly children: React.ReactElement<{readonly children: React.ReactNode}>;
}> = ({children}) => {
  const {durationInFrames, fps} = useVideoConfig();
  const scenesTotal = React.Children.toArray(children.props.children).reduce<number>(
    (sum, child) =>
      React.isValidElement<{durationInFrames?: number}>(child)
        ? sum + (child.props.durationInFrames ?? 0)
        : sum,
    0,
  );

  if (scenesTotal > MAX_DURATION_IN_FRAMES || durationInFrames > MAX_DURATION_IN_FRAMES) {
    throw new Error(
      `ProductVideo is too long: the scenes add up to ${scenesTotal} frames (${(scenesTotal / fps).toFixed(1)} s) and the composition is ${durationInFrames} frames; the cap is ${MAX_DURATION_IN_FRAMES} frames (60 s). Shorten a scene in ProductVideo.tsx.`,
    );
  }
  if (scenesTotal !== durationInFrames) {
    throw new Error(
      `ProductVideo: the scenes add up to ${scenesTotal} frames but the composition is ${durationInFrames} frames. Set durationInFrames={${scenesTotal}} on <Composition id="ProductVideo"> in Root.tsx.`,
    );
  }

  return children;
};

export const ProductVideo: React.FC = () => {
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: COLORS.background}}>
      <TimelineCheck>
        <Series>
          <Series.Sequence name="1 Alex arrives" durationInFrames={240} premountFor={fps}>
            <ArriveScene />
          </Series.Sequence>
          <Series.Sequence name="2 The graph" durationInFrames={330} premountFor={fps}>
            <GraphScene />
          </Series.Sequence>
          <Series.Sequence name="3 Dr. Wu" durationInFrames={330} premountFor={fps}>
            <DrWuScene />
          </Series.Sequence>
          <Series.Sequence name="4 The honest gap" durationInFrames={330} premountFor={fps}>
            <GapScene />
          </Series.Sequence>
          <Series.Sequence name="5 People" durationInFrames={240} premountFor={fps}>
            <PeopleScene />
          </Series.Sequence>
          <Series.Sequence name="6 Close" durationInFrames={270} premountFor={fps}>
            <CloseScene />
          </Series.Sequence>
        </Series>
      </TimelineCheck>
    </AbsoluteFill>
  );
};
