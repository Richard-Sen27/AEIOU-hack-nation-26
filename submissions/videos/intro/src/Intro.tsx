import React from 'react';
import {AbsoluteFill, getStaticFiles, staticFile, useVideoConfig} from 'remotion';
import {Audio} from '@remotion/media';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {loadFont} from '@remotion/google-fonts/Inter';
import {TitleScene} from './TitleScene';
import {PhotoScene} from './PhotoScene';
import {TeamScene} from './TeamScene';
import {OutroScene} from './OutroScene';
import {COLORS, FONT_FALLBACK} from './theme';
import {CLIPS, clipSeconds, type ClipId} from './content';

import school from '../images/Gymnasium_Neusiedl.jpg';
import mindstorm from '../images/mindstorm.jpg';
import france1 from '../images/Frankreich.png';
import france2 from '../images/Frankreich_2.png';
import lszHackathon from '../images/LSZ Hackaton 2024_124_wahl.png';
import daiHouse from '../images/IMG_7206.png';
import teamPizza from '../images/Lorenz_Felix_Paul_Richard.png';
import lorenzPortrait from '../images/Lorenz_Portrait.png';
import paulPortrait from '../images/Paul_Portait.png';
import richardPortrait from '../images/Richard_Portrait.png';

const {fontFamily} = loadFont('normal', {
  weights: ['400', '500', '600', '700', '800', '900'],
  subsets: ['latin'],
});

const TRANSITION = 18;

const transition = () => (
  <TransitionSeries.Transition
    presentation={fade()}
    timing={linearTiming({durationInFrames: TRANSITION})}
  />
);

const FPS = 30;
// Frames of quiet after a clip ends, before the next fade starts.
const BREATH = 8;
// The title scene has no incoming fade; its clip starts once "Amber" has popped in.
const TITLE_LEAD = 15;
// How long the last scene stays on screen after the final clip.
const OUTRO_HOLD = 60;

// Scenes in playback order, each with the clip spoken over it.
const SCENE_CLIPS = {
  title: 'hello',
  school: 'school',
  mindstorm: 'robotics',
  pizza: 'vienna',
  lsz: 'hackathons',
  france1: 'challenges',
  france2: 'goal',
  dai: 'awards',
  team: 'challenge',
  outro: 'decision',
} as const satisfies Record<string, ClipId>;

type SceneId = keyof typeof SCENE_CLIPS;
const SCENE_ORDER = Object.keys(SCENE_CLIPS) as SceneId[];

// A clip starts once its picture has fully faded in, and ends BREATH frames
// before the fade to the next picture begins, so no word plays over a fade.
const leadFrames = (scene: SceneId) =>
  scene === SCENE_ORDER[0] ? TITLE_LEAD : TRANSITION;

const sceneFrames = (scene: SceneId) =>
  leadFrames(scene) +
  Math.ceil(clipSeconds(SCENE_CLIPS[scene]) * FPS) +
  BREATH +
  (scene === SCENE_ORDER[SCENE_ORDER.length - 1] ? OUTRO_HOLD : TRANSITION);

export const SCENES = Object.fromEntries(
  SCENE_ORDER.map((scene) => [scene, sceneFrames(scene)]),
) as Record<SceneId, number>;

export const TOTAL_DURATION =
  Object.values(SCENES).reduce((a, b) => a + b, 0) -
  (Object.keys(SCENES).length - 1) * TRANSITION;

// Plays the scene's clip if public/ holds it; silent until it is generated.
const Voiceover: React.FC<{scene: SceneId}> = ({scene}) => {
  const {fps} = useVideoConfig();
  const file = CLIPS[SCENE_CLIPS[scene]].voiceover;
  if (!getStaticFiles().some((f) => f.name === file)) {
    return null;
  }
  return (
    <Audio
      name={`Voiceover ${scene}`}
      src={staticFile(file)}
      from={leadFrames(scene)}
      premountFor={fps}
    />
  );
};

export const Intro: React.FC = () => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.background,
        fontFamily: `${fontFamily}, ${FONT_FALLBACK}`,
      }}
    >
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={SCENES.title}>
          <TitleScene />
          <Voiceover scene="title" />
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.school}>
          <PhotoScene
            src={school}
            eyebrow="Neusiedl am See, Austria"
            caption="It all started at Gymnasium Neusiedl"
            durationInFrames={SCENES.school}
          />
          <Voiceover scene="school" />
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.mindstorm}>
          <PhotoScene
            src={mindstorm}
            eyebrow="First steps"
            caption="Building our first robots with LEGO Mindstorms"
            durationInFrames={SCENES.mindstorm}
            zoomDirection={-1}
            containOnBlur
          />
          <Voiceover scene="mindstorm" />
        </TransitionSeries.Sequence>
        {transition()}

        {/* Stand-in for the Vienna schools (Spengergasse, Rennweg) until a photo exists. */}
        <TransitionSeries.Sequence durationInFrames={SCENES.pizza}>
          <PhotoScene
            src={teamPizza}
            eyebrow="One team"
            caption="Fueled by pizza and big ideas"
            durationInFrames={SCENES.pizza}
            objectPosition="50% 40%"
          />
          <Voiceover scene="pizza" />
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.lsz}>
          <PhotoScene
            src={lszHackathon}
            eyebrow="LSZ Hackathon 2024"
            caption="Then hackathons became our thing"
            durationInFrames={SCENES.lsz}
            objectPosition="50% 35%"
          />
          <Voiceover scene="lsz" />
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.france1}>
          <PhotoScene
            src={france1}
            eyebrow="Hackathon in France"
            caption="Hacking together across borders"
            durationInFrames={SCENES.france1}
          />
          <Voiceover scene="france1" />
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.france2}>
          <PhotoScene
            src={france2}
            eyebrow="Hackathon in France"
            caption="Friends first, teammates always"
            durationInFrames={SCENES.france2}
            zoomDirection={-1}
          />
          <Voiceover scene="france2" />
        </TransitionSeries.Sequence>
        {transition()}

        {/* Stand-in for the national AI championship (BWKI) and AI for Green award until photos exist. */}
        <TransitionSeries.Sequence durationInFrames={SCENES.dai}>
          <PhotoScene
            src={daiHouse}
            eyebrow="dAGI House"
            caption="Shipping AI projects together"
            durationInFrames={SCENES.dai}
            zoomDirection={-1}
            containOnBlur
          />
          <Voiceover scene="dai" />
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.team}>
          <TeamScene
            members={[
              {
                name: 'Lorenz Schmidt',
                linkedin: 'in/lorenz-schmidt2',
                portrait: lorenzPortrait,
              },
              {
                name: 'Paul Wenth',
                linkedin: 'in/paul-wenth',
                portrait: paulPortrait,
                position: '50% 20%',
              },
              {
                name: 'Richard Senger',
                linkedin: 'in/rs-richard-senger',
                portrait: richardPortrait,
              },
            ]}
          />
          <Voiceover scene="team" />
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.outro}>
          <OutroScene />
          <Voiceover scene="outro" />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
