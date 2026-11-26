import React from 'react';
import {Composition, CalculateMetadataFunction} from 'remotion';
import {Reel, ReelProps, defaultReelProps} from './Reel';

const calc: CalculateMetadataFunction<ReelProps> = ({props}) => ({
  durationInFrames: Math.max(1, Math.round(props.durationSec * props.fps)),
  fps: props.fps,
  width: props.width,
  height: props.height,
});

export const Root: React.FC = () => (
  <Composition
    id="Reel"
    component={Reel}
    durationInFrames={300}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={defaultReelProps}
    calculateMetadata={calc}
  />
);
