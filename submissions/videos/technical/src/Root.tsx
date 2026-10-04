import {Composition, Folder} from 'remotion';
import {AgentScene} from './scenes/AgentScene';
import {AtlasScene} from './scenes/AtlasScene';
import {ClustersScene} from './scenes/ClustersScene';
import {ConfidenceScene} from './scenes/ConfidenceScene';
import {ExtractScene} from './scenes/ExtractScene';
import {SourcesScene} from './scenes/SourcesScene';
import {TechnicalVideo} from './TechnicalVideo';

// Scene durations here are for previewing a scene on its own; keep them equal
// to the matching <Series.Sequence> in TechnicalVideo.tsx.
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="TechnicalVideo"
        component={TechnicalVideo}
        durationInFrames={1788}
        fps={30}
        width={1920}
        height={1080}
      />
      <Folder name="Scenes">
        <Composition
          id="Scene1-Sources"
          component={SourcesScene}
          durationInFrames={242}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene2-Extract"
          component={ExtractScene}
          durationInFrames={322}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene3-Confidence"
          component={ConfidenceScene}
          durationInFrames={323}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene4-Clusters"
          component={ClustersScene}
          durationInFrames={277}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene5-Agent"
          component={AgentScene}
          durationInFrames={347}
          fps={30}
          width={1920}
          height={1080}
        />
        <Composition
          id="Scene6-Atlas"
          component={AtlasScene}
          durationInFrames={277}
          fps={30}
          width={1920}
          height={1080}
        />
      </Folder>
    </>
  );
};
