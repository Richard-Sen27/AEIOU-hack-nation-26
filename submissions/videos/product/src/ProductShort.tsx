import React from 'react';
import {AbsoluteFill, Series, useVideoConfig} from 'remotion';
import {ArriveScene} from './scenes/ArriveScene';
import {CloseScene} from './scenes/CloseScene';
import {GapScene} from './scenes/GapScene';
import {GraphScene} from './scenes/GraphScene';
import {RelativeScene} from './scenes/RelativeScene';
import {COLORS} from './theme';

// The scenes that can be recorded signed out, as a 47-second cut: scenes 1, 2,
// a stand-in for 3 (the related disease on the node page), 4 and 6.
export const ProductShort: React.FC = () => {
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: COLORS.background}}>
      <Series>
        <Series.Sequence name="1 Alex arrives" durationInFrames={252} premountFor={fps}>
          <ArriveScene />
        </Series.Sequence>
        <Series.Sequence name="2 The graph" durationInFrames={338} premountFor={fps}>
          <GraphScene />
        </Series.Sequence>
        <Series.Sequence name="3 A hidden relative" durationInFrames={240} premountFor={fps}>
          <RelativeScene />
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
