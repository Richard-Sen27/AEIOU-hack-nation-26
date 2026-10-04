import {Composition, Folder} from 'remotion';
import {Caption} from './components/Caption';
import {LogoOutro} from './components/LogoOutro';
import {SCENES} from './content';
import {ProductVideo} from './ProductVideo';
import {ArriveScene} from './scenes/ArriveScene';
import {CloseScene} from './scenes/CloseScene';
import {DrWuScene} from './scenes/DrWuScene';
import {GapScene} from './scenes/GapScene';
import {GraphScene} from './scenes/GraphScene';
import {PeopleScene} from './scenes/PeopleScene';

// Scene durations here are for previewing a scene on its own; keep them equal
// to the matching <Series.Sequence> in ProductVideo.tsx.
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ProductVideo"
        component={ProductVideo}
        durationInFrames={1713}
        fps={30}
        width={1920}
        height={1080}
      />
      <Folder name="Scenes">
        <Composition
          id="Scene1-Arrive"
          component={ArriveScene}
          durationInFrames={252}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene2-Graph"
          component={GraphScene}
          durationInFrames={338}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene3-DrWu"
          component={DrWuScene}
          durationInFrames={312}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene4-Gap"
          component={GapScene}
          durationInFrames={324}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene5-People"
          component={PeopleScene}
          durationInFrames={237}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene6-Close"
          component={CloseScene}
          durationInFrames={250}
          fps={30}
          width={1920}
          height={1080}
        />
      </Folder>
      <Folder name="Elements">
        <Composition
          id="Caption"
          component={Caption}
          durationInFrames={150}
          fps={30}
          width={1920}
          height={1080}
          defaultProps={{children: SCENES['dr-wu'].caption}}
        />
        <Composition
          id="LogoOutro"
          component={LogoOutro}
          durationInFrames={102}
          fps={30}
          width={1920}
          height={1080}
        />
      </Folder>
    </>
  );
};
