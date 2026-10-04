import {Audio, Video} from '@remotion/media';
import type React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Caption} from '../components/Caption';
import {RecordingFrame, SceneLayout} from '../components/SceneLayout';
import {ScenePlaceholder} from '../components/ScenePlaceholder';
import {SCENES} from '../content';
import {usePublicFile} from '../use-public-file';

const scene = SCENES['dr-wu'];

export const DrWuScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const recordingSrc = usePublicFile(scene.recording);
  const voiceoverSrc = usePublicFile(scene.voiceover);

  return (
    <SceneLayout>
      <RecordingFrame>
        {recordingSrc ? (
          // Editing knobs: trimBefore = first frame of the take to show (30 per second),
          // playbackRate = speed (2 plays twice as fast).
          <Video
            key={recordingSrc}
            name="Recording"
            src={recordingSrc}
            muted
            trimBefore={0}
            playbackRate={1}
            objectFit="contain"
            premountFor={fps}
            style={{width: '100%', height: '100%'}}
          />
        ) : (
          <ScenePlaceholder scene={scene} />
        )}
      </RecordingFrame>
      <Caption
        name="Caption"
        from={45}
        durationInFrames={255}
        premountFor={fps}
        style={{
          opacity: interpolate(frame, [45, 57, 288, 300], [0, 1, 1, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }),
        }}
      >
        {scene.caption}
      </Caption>
      {voiceoverSrc ? (
        <Audio
          key={voiceoverSrc}
          name="Voiceover"
          src={voiceoverSrc}
          volume={1}
          premountFor={fps}
        />
      ) : null}
    </SceneLayout>
  );
};
