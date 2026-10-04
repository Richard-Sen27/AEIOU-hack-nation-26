import React from 'react';
import {AbsoluteFill, Series, useVideoConfig} from 'remotion';
import {CloseScene} from './scenes/CloseScene';
import {GapScene} from './scenes/GapScene';
import {GraphScene} from './scenes/GraphScene';
import {COLORS} from './theme';

// The three scenes that have recordings (2, 4 and 6), as a 30-second cut.
export const ProductShort: React.FC = () => {
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: COLORS.background}}>
      <Series>
        <Series.Sequence name="2 The graph" durationInFrames={338} premountFor={fps}>
          <GraphScene />
        </Series.Sequence>
        <Series.Sequence name="4 The honest gap" durationInFrames={324} premountFor={fps}>
          <GapScene />
        </Series.Sequence>
        <Series.Sequence name="6 Close" durationInFrames={250} premountFor={fps}>
          <CloseScene />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
