import React from 'react';
import {AbsoluteFill, Img, getStaticFiles, staticFile, useVideoConfig} from 'remotion';
import {Audio} from '@remotion/media';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {loadFont} from '@remotion/google-fonts/Inter';
import {PhotoScene} from './PhotoScene';
import {TeamScene} from './TeamScene';
import {OutroScene} from './OutroScene';
import {COLORS, FONT_FALLBACK} from './theme';
import {CLIPS, clipSeconds, type ClipId} from './content';

import teamSlide from '../images/team-slide.png';
import viennaSchools from '../images/vienna-schools.jpg';
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
// Frames of quiet after a scene's last clip, before the next fade starts.
const BREATH = 8;
// Frames of quiet between two clips spoken over the same picture.
const CLIP_GAP = 6;
// The title scene has no incoming fade; its clip starts almost at once.
const TITLE_LEAD = 6;
// How long the last scene stays on screen after the final clip.
const OUTRO_HOLD = 60;

// Scenes in playback order, each with the clips spoken over it.
const SCENE_CLIPS = {
  title: ['hello'],
  school: ['studies', 'school'],
  mindstorm: ['robotics'],
  vienna: ['vienna'],
  france1: ['hackathons'],
  france2: ['challenges'],
  lsz: ['goal'],
  dai: ['awards'],
  pizza: ['challenge'],
  team: ['members'],
  outro: ['decision'],
} as const satisfies Record<string, readonly ClipId[]>;

type SceneId = keyof typeof SCENE_CLIPS;
const SCENE_ORDER = Object.keys(SCENE_CLIPS) as SceneId[];

const clipFrames = (clip: ClipId) => Math.ceil(clipSeconds(clip) * FPS);

// Where each of the scene's clips starts, in frames from the scene's start.
// The first starts once the picture has fully faded in; the last ends BREATH
// frames before the fade to the next picture begins, so no word plays over a fade.
const clipStarts = (scene: SceneId): number[] => {
  let at = scene === SCENE_ORDER[0] ? TITLE_LEAD : TRANSITION;
  return SCENE_CLIPS[scene].map((clip) => {
    const start = at;
    at += clipFrames(clip) + CLIP_GAP;
    return start;
  });
};

const sceneFrames = (scene: SceneId) => {
  const clips = SCENE_CLIPS[scene];
  const last = clips[clips.length - 1];
  const speechEnd = clipStarts(scene)[clips.length - 1] + clipFrames(last);
  const isLast = scene === SCENE_ORDER[SCENE_ORDER.length - 1];
  return speechEnd + BREATH + (isLast ? OUTRO_HOLD : TRANSITION);
};

export const SCENES = Object.fromEntries(
  SCENE_ORDER.map((scene) => [scene, sceneFrames(scene)]),
) as Record<SceneId, number>;

export const TOTAL_DURATION =
  Object.values(SCENES).reduce((a, b) => a + b, 0) -
  (Object.keys(SCENES).length - 1) * TRANSITION;

// Plays the scene's clips that public/ holds; silent until they are generated.
const Voiceover: React.FC<{scene: SceneId}> = ({scene}) => {
  const {fps} = useVideoConfig();
  const available = new Set(getStaticFiles().map((f) => f.name));
  const starts = clipStarts(scene);
  return (
    <>
      {SCENE_CLIPS[scene].map((clip, i) =>
        available.has(CLIPS[clip].voiceover) ? (
          <Audio
            key={clip}
            name={`Voiceover ${clip}`}
            src={staticFile(CLIPS[clip].voiceover)}
            from={starts[i]}
            premountFor={fps}
          />
        ) : null,
      )}
    </>
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
          <Img src={teamSlide} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
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

        <TransitionSeries.Sequence durationInFrames={SCENES.vienna}>
          <PhotoScene
            src={viennaSchools}
            eyebrow="Vienna"
            caption="HTL Spengergasse and HTL Rennweg"
            durationInFrames={SCENES.vienna}
          />
          <Voiceover scene="vienna" />
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
