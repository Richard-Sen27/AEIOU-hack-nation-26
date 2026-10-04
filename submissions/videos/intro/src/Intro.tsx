import React from 'react';
import {AbsoluteFill} from 'remotion';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {loadFont} from '@remotion/google-fonts/Inter';
import {TitleScene} from './TitleScene';
import {PhotoScene} from './PhotoScene';
import {TeamScene} from './TeamScene';
import {OutroScene} from './OutroScene';
import {COLORS, FONT_FALLBACK} from './theme';

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

export const SCENES = {
  title: 170,
  school: 200,
  mindstorm: 180,
  france1: 200,
  france2: 180,
  lsz: 200,
  dai: 200,
  pizza: 200,
  team: 300,
  outro: 180,
};

export const TOTAL_DURATION =
  Object.values(SCENES).reduce((a, b) => a + b, 0) -
  (Object.keys(SCENES).length - 1) * TRANSITION;

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
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.school}>
          <PhotoScene
            src={school}
            eyebrow="Neusiedl am See, Austria"
            caption="It all started at Gymnasium Neusiedl"
            durationInFrames={SCENES.school}
          />
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
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.france1}>
          <PhotoScene
            src={france1}
            eyebrow="Hackathon in France"
            caption="Hacking together across borders"
            durationInFrames={SCENES.france1}
          />
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
        </TransitionSeries.Sequence>
        {transition()}

        <TransitionSeries.Sequence durationInFrames={SCENES.outro}>
          <OutroScene />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
