import React from 'react';
import {Composition} from 'remotion';
import {Intro, TOTAL_DURATION} from './Intro';

export const Root: React.FC = () => {
  return (
    <Composition
      id="Intro"
      component={Intro}
      durationInFrames={TOTAL_DURATION}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
