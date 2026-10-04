import React from 'react';
import {AbsoluteFill, Series, useVideoConfig} from 'remotion';
import {SCENES, VOICE_DELAY} from './content';
import {AgentScene} from './scenes/AgentScene';
import {AtlasScene} from './scenes/AtlasScene';
import {ClustersScene} from './scenes/ClustersScene';
import {ConfidenceScene} from './scenes/ConfidenceScene';
import {ExtractScene} from './scenes/ExtractScene';
import {SourcesScene} from './scenes/SourcesScene';
import {COLORS} from './theme';

// Hackathon rule: the submission must not exceed 60 seconds.
export const MAX_DURATION_IN_FRAMES = 1800;

// The voiceover clip each <Series.Sequence> plays, in timeline order.
const VOICE_ORDER = [
  SCENES.sources,
  SCENES.extract,
  SCENES.confidence,
  SCENES.clusters,
  SCENES.agent,
  SCENES.atlas,
] as const;

// Fails the preview and any render when the timeline stops adding up: more
// than the 60 s cap, a total that differs from the composition's duration,
// or a scene too short for its voiceover.
const TimelineCheck: React.FC<{
  readonly children: React.ReactElement<{readonly children: React.ReactNode}>;
}> = ({children}) => {
  const {durationInFrames, fps} = useVideoConfig();
  const scenes = React.Children.toArray(children.props.children).filter((child) =>
    React.isValidElement<{durationInFrames?: number}>(child),
  ) as React.ReactElement<{durationInFrames: number; name: string}>[];
  const scenesTotal = scenes.reduce((sum, s) => sum + s.props.durationInFrames, 0);

  if (scenesTotal > MAX_DURATION_IN_FRAMES || durationInFrames > MAX_DURATION_IN_FRAMES) {
    throw new Error(
      `TechnicalVideo is too long: the scenes add up to ${scenesTotal} frames (${(scenesTotal / fps).toFixed(2)} s) and the composition is ${durationInFrames} frames; the cap is ${MAX_DURATION_IN_FRAMES} frames (60 s). Shorten a scene in TechnicalVideo.tsx.`,
    );
  }
  if (scenesTotal !== durationInFrames) {
    throw new Error(
      `TechnicalVideo: the scenes add up to ${scenesTotal} frames but the composition is ${durationInFrames} frames. Set durationInFrames={${scenesTotal}} on <Composition id="TechnicalVideo"> in Root.tsx.`,
    );
  }
  scenes.forEach((s, i) => {
    const needed = VOICE_DELAY + VOICE_ORDER[i].voiceFrames;
    if (s.props.durationInFrames < needed) {
      throw new Error(
        `TechnicalVideo: scene "${s.props.name}" is ${s.props.durationInFrames} frames but its voiceover needs ${needed}. Lengthen the scene or shorten its narration.`,
      );
    }
  });

  return children;
};

export const TechnicalVideo: React.FC = () => {
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: COLORS.background}}>
      <TimelineCheck>
        <Series>
          <Series.Sequence name="1 Sources" durationInFrames={242} premountFor={fps}>
            <SourcesScene />
          </Series.Sequence>
          <Series.Sequence name="2 Verified extraction" durationInFrames={322} premountFor={fps}>
            <ExtractScene />
          </Series.Sequence>
          <Series.Sequence name="3 Confidence" durationInFrames={323} premountFor={fps}>
            <ConfidenceScene />
          </Series.Sequence>
          <Series.Sequence name="4 Clusters by mechanism" durationInFrames={277} premountFor={fps}>
            <ClustersScene />
          </Series.Sequence>
          <Series.Sequence name="5 Checked agent" durationInFrames={347} premountFor={fps}>
            <AgentScene />
          </Series.Sequence>
          <Series.Sequence name="6 Atlas" durationInFrames={259} premountFor={fps}>
            <AtlasScene />
          </Series.Sequence>
        </Series>
      </TimelineCheck>
    </AbsoluteFill>
  );
};
