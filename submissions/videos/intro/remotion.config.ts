import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
// Composition is 1920x1080; render at 2x for a 3840x2160 (4K) output.
Config.setScale(2);
