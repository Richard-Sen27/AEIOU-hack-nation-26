import {Audio, Video} from '@remotion/media';
import type React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Caption} from '../components/Caption';
import {LogoOutro} from '../components/LogoOutro';
import {RecordingFrame, SceneLayout} from '../components/SceneLayout';
import {ScenePlaceholder} from '../components/ScenePlaceholder';
import {SCENES} from '../content';
import {usePublicFile} from '../use-public-file';

const scene = SCENES.close;

// The logo outro fades in over the recording as the last sentence is spoken
// (about 5 s in) and holds to the end.
export const CloseScene: React.FC = () => {
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
            durationInFrames={165}
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
        from={30}
        durationInFrames={105}
        premountFor={fps}
        style={{
          opacity: interpolate(frame, [30, 42, 123, 135], [0, 1, 1, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }),
        }}
      >
        {scene.caption}
      </Caption>
      <LogoOutro
        name="Logo outro"
        from={148}
        durationInFrames={102}
        premountFor={fps}
        style={{
          opacity: interpolate(frame, [148, 160], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }),
        }}
      />
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
